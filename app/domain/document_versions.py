"""人工审核版本及追加式审核动作。"""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from app.domain.documents import DocumentType


class DocumentVersionStatus(StrEnum):
    """人工版本的可编辑与终结状态。"""

    DRAFT = "draft"
    APPROVED = "approved"
    REJECTED = "rejected"


class DocumentVersion(BaseModel):
    """人工审核产生的版本快照；Approved/Rejected 后不可覆盖。"""

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
    """记录谁在何时对哪个版本执行了什么动作及原因。"""

    action_id: str
    version_id: str
    actor_user_id: str
    action: str
    field_path: str | None = None
    old_value: Any = None
    new_value: Any = None
    reason: str | None = None
    created_at: datetime
