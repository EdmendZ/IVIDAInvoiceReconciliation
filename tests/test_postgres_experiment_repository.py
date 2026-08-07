from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.evaluation.models import (
    ComparisonCounts,
    DocumentEvaluation,
    EvaluationSummary,
)
from app.experiments.domain import (
    DatasetIdentity,
    ErrorSlice,
    EvaluationRun,
    EvaluationRunStatus,
    ExperimentDefinition,
    ExperimentRole,
    ExperimentThresholds,
    FeedbackCandidate,
    FeedbackClassification,
    PromotionCheck,
    PromotionDecision,
    PromotionOutcome,
)
from app.infra.database import Base
from app.infra.postgres_experiment_repository import (
    ExperimentTransitionError,
    PostgresExperimentRepository,
)


NOW = datetime(2026, 8, 7, tzinfo=UTC)


@pytest.fixture
def repository() -> PostgresExperimentRepository:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return PostgresExperimentRepository(
        sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    )


def _definition() -> ExperimentDefinition:
    return ExperimentDefinition(
        experiment_id="experiment-1",
        name="baseline",
        role=ExperimentRole.BASELINE,
        manifest_path="evaluation_data/manifest.json",
        dataset_identity=DatasetIdentity(
            version="2.0.0", manifest_sha256="a" * 64, document_sha256s=("b" * 64,)
        ),
        parser_provider="mineru",
        parser_model="vlm",
        parser_version="1",
        normalizer_provider="openai-compatible",
        normalizer_model="model",
        prompt_version="prompt",
        schema_version="schema",
        parameters={"temperature": 0},
        thresholds=ExperimentThresholds(),
        created_by="admin-1",
        created_at=NOW,
    )


def _document(valid: bool) -> DocumentEvaluation:
    return DocumentEvaluation(
        case_id="case-1",
        business_scenario="exact",
        document_path="a.pdf",
        document_type="invoice",
        schema_valid=valid,
        counts=ComparisonCounts(
            correct=1 if valid else 0,
            total=1,
            matched_lines=0,
            missing_lines=0,
            extra_lines=0,
            evidence_covered=0,
            evidence_total=1,
            errors=[],
        ),
        latency_ms=1,
        parser_cache_hit=True,
        parser_model="vlm",
        normalizer_model="model",
        prompt_version="prompt",
        error_stage=None if valid else "normalizing",
    )


def _summary() -> EvaluationSummary:
    return EvaluationSummary(
        variant_name="baseline",
        document_count=2,
        schema_valid_rate=Decimal("0.5"),
        field_micro_accuracy=Decimal("0.5"),
        line_item_f1=Decimal("1"),
        evidence_coverage=Decimal("0"),
        p50_latency_ms=1,
        p95_latency_ms=1,
        parser_cache_hits=2,
    )


def test_completion_preserves_failed_documents(repository) -> None:
    definition = repository.create_definition(_definition())
    queued = EvaluationRun(
        run_id="run-1",
        experiment_id=definition.experiment_id,
        status=EvaluationRunStatus.QUEUED,
        created_at=NOW,
    )
    repository.create_run(queued)
    repository.mark_run_running(queued.run_id, started_at=NOW)

    completed = repository.complete_run(
        queued.run_id,
        summary=_summary(),
        documents=[_document(True), _document(False)],
        slices=[
            ErrorSlice(
                dimension="error_type",
                value="schema_failure",
                document_count=1,
                error_count=1,
            )
        ],
        completed_at=NOW + timedelta(seconds=1),
    )

    assert completed.status == EvaluationRunStatus.COMPLETED
    assert len(completed.documents) == completed.summary.document_count == 2
    with pytest.raises(ExperimentTransitionError):
        repository.cancel_run(queued.run_id, cancelled_at=NOW)


def test_cancelled_run_cannot_complete(repository) -> None:
    repository.create_definition(_definition())
    repository.create_run(
        EvaluationRun(
            run_id="run-2",
            experiment_id="experiment-1",
            status=EvaluationRunStatus.QUEUED,
            created_at=NOW,
        )
    )
    cancelled = repository.cancel_run("run-2", cancelled_at=NOW)
    assert cancelled.status == EvaluationRunStatus.CANCELLED
    with pytest.raises(ExperimentTransitionError):
        repository.mark_run_running("run-2", started_at=NOW)


def test_summary_count_must_include_every_document(repository) -> None:
    repository.create_definition(_definition())
    repository.create_run(
        EvaluationRun(
            run_id="run-3",
            experiment_id="experiment-1",
            status=EvaluationRunStatus.QUEUED,
            created_at=NOW,
        )
    )
    repository.mark_run_running("run-3", started_at=NOW)
    with pytest.raises(ValueError, match="every document"):
        repository.complete_run(
            "run-3",
            summary=_summary(),
            documents=[_document(True)],
            slices=[],
            completed_at=NOW,
        )


def test_only_confirmed_model_errors_can_enter_gold(repository) -> None:
    candidate = FeedbackCandidate(
        candidate_id="feedback-1",
        task_id="task-1",
        draft_id="draft-1",
        version_id="version-1",
        action_id="action-1",
        run_id="run-1",
        field_path="document_number",
        old_value="INV-01",
        new_value="INV-001",
        document_type="invoice",
        normalizer_model="model",
        prompt_version="prompt",
        created_at=NOW,
    )
    repository.create_feedback_candidates([candidate])

    confirmed = repository.confirm_feedback(
        candidate.candidate_id,
        classification=FeedbackClassification.ACCEPTABLE_VARIANT,
        include_in_gold=True,
        confirmed_by="admin-1",
        confirmed_at=NOW,
    )

    assert confirmed.classification == FeedbackClassification.ACCEPTABLE_VARIANT
    assert confirmed.include_in_gold is False
    assert repository.list_feedback_candidates(confirmed=True) == [confirmed]


def test_promotion_decision_round_trips(repository) -> None:
    decision = PromotionDecision(
        decision_id="decision-1",
        baseline_run_id="baseline-run",
        candidate_run_id="candidate-run",
        outcome=PromotionOutcome.REJECTED,
        checks=[
            PromotionCheck(
                code="schema_valid_rate",
                hard_gate=True,
                passed=False,
                candidate_value="0.98",
                threshold="1.0",
                reason="candidate did not meet the schema-validity gate",
            )
        ],
        reasons=["hard gate failed"],
        decided_by="admin-1",
        decided_at=NOW,
    )

    repository.save_decision(decision)

    assert repository.get_decision(decision.decision_id) == decision
