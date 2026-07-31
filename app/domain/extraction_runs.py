"""一次文档处理尝试的领域对象与细粒度状态机。"""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, Field


class ExtractionRunStatus(StrEnum):
    """Worker 可推进的阶段和终态。"""

    QUEUED = "queued"
    SUBMITTING = "submitting"
    PARSING = "parsing"
    NORMALIZING = "normalizing"
    VALIDATING = "validating"
    READY_FOR_REVIEW = "ready_for_review"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ExtractionRun(BaseModel):
    """记录一次 Parser/Normalizer 尝试、调度、成本、错误和取消信息。"""

    run_id: str
    task_id: str
    provider: str
    model_name: str
    status: ExtractionRunStatus
    raw_output: dict | None = None
    normalized_output: dict | None = None
    latency_ms: int | None = Field(default=None, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    estimated_cost_aud: Decimal | None = Field(default=None, ge=0)
    error_message: str | None = None
    phase_error_code: str | None = None
    remote_job_id: str | None = None
    attempt_count: int = Field(default=0, ge=0)
    next_attempt_at: datetime | None = None
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    started_at: datetime
    completed_at: datetime | None = None
    cancel_requested_at: datetime | None = None
    cancel_requested_by: str | None = None
    cancel_completed_at: datetime | None = None
    cancelled_stage: str | None = None
    remote_may_continue: bool = False
    parser_provider: str | None = None
    parser_model: str | None = None
    normalizer_provider: str | None = None
    normalizer_model: str | None = None
    prompt_version: str | None = None
    normalization_latency_ms: int | None = Field(default=None, ge=0)
    created_at: datetime
