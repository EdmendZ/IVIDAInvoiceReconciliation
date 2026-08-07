"""Domain contracts for reproducible extraction quality experiments."""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.evaluation.models import DocumentEvaluation, EvaluationSummary


class ExperimentRole(StrEnum):
    BASELINE = "baseline"
    CANDIDATE = "candidate"


class EvaluationRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class FeedbackClassification(StrEnum):
    MODEL_ERROR = "model_error"
    ACCEPTABLE_VARIANT = "acceptable_variant"
    REVIEWER_CORRECTION_ERROR = "reviewer_correction_error"
    BUSINESS_CONTEXT_UPDATE = "business_context_update"


class PromotionOutcome(StrEnum):
    RECOMMENDED = "recommended"
    REJECTED = "rejected"
    INCONCLUSIVE = "inconclusive"


class DatasetIdentity(BaseModel):
    model_config = ConfigDict(frozen=True)

    version: str = Field(min_length=1)
    manifest_sha256: str = Field(min_length=64, max_length=64)
    document_sha256s: tuple[str, ...] = Field(min_length=1)

    @field_validator("document_sha256s")
    @classmethod
    def normalize_hashes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(len(value) != 64 for value in values):
            raise ValueError("document hashes must be SHA-256 hex digests")
        if len(set(values)) != len(values):
            raise ValueError("document hashes must be unique")
        return tuple(sorted(values))


class ExperimentThresholds(BaseModel):
    model_config = ConfigDict(frozen=True)

    required_schema_valid_rate: Decimal = Field(default=Decimal("1"), ge=0, le=1)
    minimum_field_accuracy: Decimal = Field(default=Decimal("0.95"), ge=0, le=1)
    minimum_line_item_f1: Decimal = Field(default=Decimal("0.95"), ge=0, le=1)
    minimum_evidence_coverage: Decimal = Field(default=Decimal("0.90"), ge=0, le=1)
    max_cost_aud_per_document: Decimal | None = Field(default=None, ge=0)
    require_known_cost: bool = False
    critical_field_paths: tuple[str, ...] = (
        "document_type",
        "document_number",
        "purchase_order_number",
        "currency",
        "items",
    )
    target_slices: tuple[str, ...] = ()


class ExperimentDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    experiment_id: str
    name: str = Field(min_length=1)
    role: ExperimentRole
    manifest_path: str = Field(min_length=1)
    dataset_identity: DatasetIdentity
    parser_provider: str
    parser_model: str
    parser_version: str
    normalizer_provider: str
    normalizer_model: str
    prompt_version: str
    schema_version: str
    parameters: dict[str, object] = Field(default_factory=dict)
    thresholds: ExperimentThresholds
    created_by: str
    created_at: datetime


class ErrorSlice(BaseModel):
    dimension: str
    value: str
    document_count: int = Field(ge=0)
    error_count: int = Field(ge=0)

    @property
    def key(self) -> str:
        return f"{self.dimension}:{self.value}"


class EvaluationRun(BaseModel):
    run_id: str
    experiment_id: str
    status: EvaluationRunStatus
    summary: EvaluationSummary | None = None
    documents: list[DocumentEvaluation] = Field(default_factory=list)
    slices: list[ErrorSlice] = Field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    cancelled_at: datetime | None = None


class FeedbackCandidate(BaseModel):
    candidate_id: str
    task_id: str
    draft_id: str
    version_id: str
    action_id: str
    run_id: str
    field_path: str
    old_value: object | None = None
    new_value: object | None = None
    document_type: str
    supplier_name: str | None = None
    normalizer_model: str
    prompt_version: str
    classification: FeedbackClassification | None = None
    include_in_gold: bool = False
    confirmed_by: str | None = None
    confirmed_at: datetime | None = None
    created_at: datetime
    supersedes_candidate_id: str | None = None


class PromotionCheck(BaseModel):
    code: str
    hard_gate: bool
    passed: bool
    baseline_value: object | None = None
    candidate_value: object | None = None
    threshold: object | None = None
    evidence_missing: bool = False
    reason: str


class PromotionDecision(BaseModel):
    decision_id: str
    baseline_run_id: str
    candidate_run_id: str
    outcome: PromotionOutcome
    checks: list[PromotionCheck]
    reasons: list[str]
    decided_by: str
    decided_at: datetime
