"""Fail-closed comparison rules for baseline and candidate experiments."""

from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from app.experiments.domain import (
    ErrorSlice,
    EvaluationRun,
    EvaluationRunStatus,
    ExperimentDefinition,
    PromotionCheck,
    PromotionDecision,
    PromotionOutcome,
)


def _slice_counts(slices: list[ErrorSlice]) -> dict[str, int]:
    return {item.key: item.error_count for item in slices}


def _critical_error_count(
    run: EvaluationRun,
    field_paths: tuple[str, ...],
) -> int:
    return sum(
        1
        for document in run.documents
        for error in document.counts.errors
        if any(
            error.startswith(path + ":") or error.startswith(path + ".")
            for path in field_paths
        )
    )


def _check(
    code: str,
    passed: bool,
    reason: str,
    *,
    hard_gate: bool = False,
    baseline: object | None = None,
    candidate: object | None = None,
    threshold: object | None = None,
    evidence_missing: bool = False,
) -> PromotionCheck:
    return PromotionCheck(
        code=code,
        hard_gate=hard_gate,
        passed=passed,
        baseline_value=baseline,
        candidate_value=candidate,
        threshold=threshold,
        evidence_missing=evidence_missing,
        reason=reason,
    )


def _build_checks(
    baseline: EvaluationRun,
    baseline_definition: ExperimentDefinition,
    candidate: EvaluationRun,
    candidate_definition: ExperimentDefinition,
) -> list[PromotionCheck]:
    thresholds = candidate_definition.thresholds
    same_dataset = (
        baseline_definition.dataset_identity
        == candidate_definition.dataset_identity
    )
    complete = (
        baseline.status == EvaluationRunStatus.COMPLETED
        and candidate.status == EvaluationRunStatus.COMPLETED
        and baseline.summary is not None
        and candidate.summary is not None
    )
    checks = [
        _check(
            "dataset_identity",
            same_dataset,
            "datasets match" if same_dataset else "dataset identities differ",
            evidence_missing=not same_dataset,
        ),
        _check(
            "runs_complete",
            complete,
            "both runs completed" if complete else "both runs must be complete",
            evidence_missing=not complete,
        ),
    ]
    if not complete:
        return checks

    assert baseline.summary is not None
    assert candidate.summary is not None
    baseline_summary = baseline.summary
    candidate_summary = candidate.summary

    checks.extend(
        [
            _check(
                "schema_valid_rate",
                candidate_summary.schema_valid_rate
                >= thresholds.required_schema_valid_rate,
                "candidate Schema valid rate meets the required floor",
                hard_gate=True,
                baseline=baseline_summary.schema_valid_rate,
                candidate=candidate_summary.schema_valid_rate,
                threshold=thresholds.required_schema_valid_rate,
            ),
            _check(
                "critical_fields",
                _critical_error_count(
                    candidate, thresholds.critical_field_paths
                )
                <= _critical_error_count(
                    baseline, thresholds.critical_field_paths
                ),
                "candidate introduces no additional critical-field errors",
                hard_gate=True,
                baseline=_critical_error_count(
                    baseline, thresholds.critical_field_paths
                ),
                candidate=_critical_error_count(
                    candidate, thresholds.critical_field_paths
                ),
                threshold="candidate <= baseline",
            ),
            _check(
                "field_accuracy",
                candidate_summary.field_micro_accuracy
                >= max(
                    baseline_summary.field_micro_accuracy,
                    thresholds.minimum_field_accuracy,
                ),
                "candidate field accuracy meets its floor without regression",
                baseline=baseline_summary.field_micro_accuracy,
                candidate=candidate_summary.field_micro_accuracy,
                threshold=thresholds.minimum_field_accuracy,
            ),
            _check(
                "line_item_f1",
                candidate_summary.line_item_f1
                >= max(
                    baseline_summary.line_item_f1,
                    thresholds.minimum_line_item_f1,
                ),
                "candidate line-item F1 meets its floor without regression",
                baseline=baseline_summary.line_item_f1,
                candidate=candidate_summary.line_item_f1,
                threshold=thresholds.minimum_line_item_f1,
            ),
            _check(
                "evidence_coverage",
                candidate_summary.evidence_coverage
                >= max(
                    baseline_summary.evidence_coverage,
                    thresholds.minimum_evidence_coverage,
                ),
                "candidate Evidence coverage meets its floor without regression",
                baseline=baseline_summary.evidence_coverage,
                candidate=candidate_summary.evidence_coverage,
                threshold=thresholds.minimum_evidence_coverage,
            ),
        ]
    )

    cost_known = candidate_summary.average_cost_aud is not None
    checks.append(
        _check(
            "cost_known",
            cost_known or not thresholds.require_known_cost,
            "candidate cost is available"
            if cost_known
            else "candidate cost is not configured",
            evidence_missing=thresholds.require_known_cost and not cost_known,
            candidate=candidate_summary.average_cost_aud,
            threshold="known" if thresholds.require_known_cost else "optional",
        )
    )
    cost_limit = thresholds.max_cost_aud_per_document
    within_cost = (
        cost_limit is None
        or (
            candidate_summary.average_cost_aud is not None
            and candidate_summary.average_cost_aud <= cost_limit
        )
    )
    checks.append(
        _check(
            "cost_limit",
            within_cost,
            "candidate cost is within the configured limit",
            hard_gate=cost_limit is not None,
            candidate=candidate_summary.average_cost_aud,
            threshold=cost_limit,
            evidence_missing=(
                cost_limit is not None
                and candidate_summary.average_cost_aud is None
            ),
        )
    )

    baseline_slices = _slice_counts(baseline.slices)
    candidate_slices = _slice_counts(candidate.slices)
    if thresholds.target_slices:
        improved = any(
            candidate_slices.get(key, 0) < baseline_slices.get(key, 0)
            for key in thresholds.target_slices
        )
    else:
        improved = any(
            candidate_value > baseline_value
            for candidate_value, baseline_value in (
                (
                    candidate_summary.field_micro_accuracy,
                    baseline_summary.field_micro_accuracy,
                ),
                (candidate_summary.line_item_f1, baseline_summary.line_item_f1),
                (
                    candidate_summary.evidence_coverage,
                    baseline_summary.evidence_coverage,
                ),
            )
        )
    checks.append(
        _check(
            "target_slice_improved",
            improved,
            "candidate improves a declared target or aggregate quality metric",
            baseline={key: baseline_slices.get(key, 0) for key in thresholds.target_slices},
            candidate={key: candidate_slices.get(key, 0) for key in thresholds.target_slices},
            threshold=list(thresholds.target_slices),
        )
    )
    return checks


def decide_promotion(
    baseline: EvaluationRun,
    baseline_definition: ExperimentDefinition,
    candidate: EvaluationRun,
    candidate_definition: ExperimentDefinition,
    *,
    decided_by: str,
    now: datetime,
) -> PromotionDecision:
    try:
        checks = _build_checks(
            baseline,
            baseline_definition,
            candidate,
            candidate_definition,
        )
        if any(not item.passed and item.evidence_missing for item in checks):
            outcome = PromotionOutcome.INCONCLUSIVE
        elif any(not item.passed and item.hard_gate for item in checks):
            outcome = PromotionOutcome.REJECTED
        elif any(
            not item.passed
            for item in checks
            if item.code != "target_slice_improved"
        ):
            outcome = PromotionOutcome.REJECTED
        elif not next(
            item for item in checks if item.code == "target_slice_improved"
        ).passed:
            outcome = PromotionOutcome.INCONCLUSIVE
        else:
            outcome = PromotionOutcome.RECOMMENDED
    except Exception as exc:
        checks = [
            _check(
                "promotion_calculation",
                False,
                f"promotion calculation failed: {type(exc).__name__}",
                evidence_missing=True,
            )
        ]
        outcome = PromotionOutcome.INCONCLUSIVE

    return PromotionDecision(
        decision_id=str(uuid4()),
        baseline_run_id=baseline.run_id,
        candidate_run_id=candidate.run_id,
        outcome=outcome,
        checks=checks,
        reasons=[item.reason for item in checks if not item.passed],
        decided_by=decided_by,
        decided_at=now,
    )
