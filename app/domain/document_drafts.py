from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel

from app.domain.documents import DocumentType
from app.domain.normalization import FieldEvidence
from app.domain.validation import ValidationIssue


class DraftValidationState(StrEnum):
    REVIEWABLE = "reviewable"
    BLOCKED = "blocked"


class DocumentDraft(BaseModel):
    draft_id: str
    run_id: str
    task_id: str
    document_type: DocumentType
    normalized_json: dict
    validation_state: DraftValidationState
    created_at: datetime
    updated_at: datetime


class DraftBundle(BaseModel):
    draft: DocumentDraft
    evidence: list[FieldEvidence]
    issues: list[ValidationIssue]
