from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from app.domain.documents import DocumentType


class ExtractionStatus(StrEnum):
    UPLOADED = "uploaded"
    EXTRACTING = "extracting"
    READY_FOR_REVIEW = "ready_for_review"
    APPROVED = "approved"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ExtractionTask(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    task_id: str
    document_type: DocumentType
    original_filename: str
    content_type: str
    size_bytes: int
    sha256: str
    storage_bucket: str
    storage_object_key: str
    purchase_order_hint: str | None = None
    status: ExtractionStatus
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime

