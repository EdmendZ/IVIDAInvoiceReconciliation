from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from app.domain.documents import DocumentType


class DocumentVersionStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    REJECTED = "rejected"


class DocumentVersion(BaseModel):
    version_id: str
    task_id: str
    source_draft_id: str
    version_number: int = Field(ge=1)
    document_type: DocumentType
    document_json: dict
    status: DocumentVersionStatus
    created_by: str
    approved_by: str | None = None
    approved_at: datetime | None = None
    created_at: datetime


class ReviewAction(BaseModel):
    action_id: str
    version_id: str
    actor_user_id: str
    action: str
    field_path: str | None = None
    old_value: Any = None
    new_value: Any = None
    reason: str | None = None
    created_at: datetime
