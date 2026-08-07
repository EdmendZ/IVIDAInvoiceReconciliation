from datetime import UTC, datetime
from decimal import Decimal

from app.evaluation.models import EvaluationSummary
from app.experiments.domain import (
    DatasetIdentity,
    ErrorSlice,
    EvaluationRun,
    EvaluationRunStatus,
    ExperimentDefinition,
    ExperimentRole,
    ExperimentThresholds,
    PromotionOutcome,
)
from app.experiments.promotion import decide_promotion
from app.experiments.reporting import render_promotion_markdown


NOW = datetime(2026, 8, 7, tzinfo=UTC)


def _definition(
    identifier: str,
    role: ExperimentRole,
    *,
    manifest_hash: str = "a" * 64,
    require_cost: bool = False,
    target_slices: tuple[str, ...] = (),
) -> ExperimentDefinition:
    return ExperimentDefinition(
        experiment_id=identifier,
        name=identifier,
        role=role,
        manifest_path="evaluation_data/manifest.json",
        dataset_identity=DatasetIdentity(
            version="1.0.0",
            manifest_sha256=manifest_hash,
            document_sha256s=("b" * 64,),
        ),
        parser_provider="mineru",
        parser_model="vlm",
        parser_version="1",
        normalizer_provider="openai-compatible",
        normalizer_model="model",
        prompt_version="prompt",
        schema_version="schema",
        thresholds=ExperimentThresholds(
            minimum_field_accuracy=Decimal("0.80"),
            minimum_line_item_f1=Decimal("0.80"),
            minimum_evidence_coverage=Decimal("0.80"),
            require_known_cost=require_cost,
            target_slices=target_slices,
        ),
        created_by="admin",
        created_at=NOW,
    )


def _run(
    identifier: str,
    experiment_id: str,
    *,
    accuracy: str,
    cost: str | None = "0.05",
    target_errors: int = 0,
    status: EvaluationRunStatus = EvaluationRunStatus.COMPLETED,
) -> EvaluationRun:
    summary = EvaluationSummary(
        variant_name=identifier,
        document_count=17,
        schema_valid_rate=Decimal("1"),
        field_micro_accuracy=Decimal(accuracy),
        line_item_f1=Decimal("0.95"),
        evidence_coverage=Decimal("0.90"),
        p50_latency_ms=100,
        p95_latency_ms=200,
        average_cost_aud=Decimal(cost) if cost is not None else None,
        total_cost_aud=(Decimal(cost) * 17 if cost is not None else None),
        parser_cache_hits=17,
    )
    return EvaluationRun(
        run_id=identifier,
        experiment_id=experiment_id,
        status=status,
        summary=summary if status == EvaluationRunStatus.COMPLETED else None,
        slices=[
            ErrorSlice(
                dimension="field_group",
                value="purchase",
                document_count=target_errors,
                error_count=target_errors,
            )
        ],
        created_at=NOW,
        completed_at=NOW if status == EvaluationRunStatus.COMPLETED else None,
    )


def test_improved_target_without_regression_is_recommended() -> None:
    baseline_definition = _definition(
        "baseline",
        ExperimentRole.BASELINE,
    )
    candidate_definition = _definition(
        "candidate",
        ExperimentRole.CANDIDATE,
        target_slices=("field_group:purchase",),
    )
    baseline = _run(
        "run-a", "baseline", accuracy="0.90", target_errors=2
    )
    candidate = _run(
        "run-b", "candidate", accuracy="0.92", target_errors=0
    )

    decision = decide_promotion(
        baseline,
        baseline_definition,
        candidate,
        candidate_definition,
        decided_by="admin",
        now=NOW,
    )

    assert decision.outcome == PromotionOutcome.RECOMMENDED
    assert decision.reasons == []


def test_unknown_required_cost_is_inconclusive() -> None:
    baseline_definition = _definition("baseline", ExperimentRole.BASELINE)
    candidate_definition = _definition(
        "candidate", ExperimentRole.CANDIDATE, require_cost=True
    )

    decision = decide_promotion(
        _run("run-a", "baseline", accuracy="0.90"),
        baseline_definition,
        _run("run-b", "candidate", accuracy="0.92", cost=None),
        candidate_definition,
        decided_by="admin",
        now=NOW,
    )

    assert decision.outcome == PromotionOutcome.INCONCLUSIVE
    assert "candidate cost is not configured" in decision.reasons


def test_dataset_mismatch_is_inconclusive() -> None:
    decision = decide_promotion(
        _run("run-a", "baseline", accuracy="0.90"),
        _definition("baseline", ExperimentRole.BASELINE),
        _run("run-b", "candidate", accuracy="0.92"),
        _definition(
            "candidate",
            ExperimentRole.CANDIDATE,
            manifest_hash="c" * 64,
        ),
        decided_by="admin",
        now=NOW,
    )

    assert decision.outcome == PromotionOutcome.INCONCLUSIVE


def test_quality_regression_is_rejected() -> None:
    decision = decide_promotion(
        _run("run-a", "baseline", accuracy="0.90"),
        _definition("baseline", ExperimentRole.BASELINE),
        _run("run-b", "candidate", accuracy="0.89"),
        _definition("candidate", ExperimentRole.CANDIDATE),
        decided_by="admin",
        now=NOW,
    )

    assert decision.outcome == PromotionOutcome.REJECTED


def test_incomplete_run_and_report_are_safe() -> None:
    decision = decide_promotion(
        _run("run-a", "baseline", accuracy="0.90"),
        _definition("baseline", ExperimentRole.BASELINE),
        _run(
            "run-b",
            "candidate",
            accuracy="0.92",
            status=EvaluationRunStatus.FAILED,
        ),
        _definition("candidate", ExperimentRole.CANDIDATE),
        decided_by="admin",
        now=NOW,
    )

    assert decision.outcome == PromotionOutcome.INCONCLUSIVE
    report = render_promotion_markdown(decision)
    assert "run-a" in report and "run-b" in report
    assert "api_key" not in report
