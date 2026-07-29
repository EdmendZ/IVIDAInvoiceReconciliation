from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, Field


class ExtractionRunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ExtractionRun(BaseModel):
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
    started_at: datetime
    completed_at: datetime | None = None
    created_at: datetime

