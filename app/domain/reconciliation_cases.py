"""Reconciliation case aggregate and read-model contracts."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator

from app.domain.reconciliation_records import ReconciliationRecord


class CaseStatus(StrEnum):
    UNASSIGNED = "unassigned"
    IN_PROGRESS = "in_progress"
    PENDING_APPROVAL = "pending_approval"
    PENDING_VOID = "pending_void"
    APPROVED = "approved"
    VOIDED = "voided"


class CaseItemType(StrEnum):
    LINE = "line"
    PURCHASE_ORDER_CONFLICT = "purchase_order_conflict"
    CURRENCY_CONFLICT = "currency_conflict"


class ResolutionType(StrEnum):
    BUSINESS_EXCEPTION = "business_exception"
    DOCUMENT_DATA_ERROR = "document_data_error"
    MATCHING_ERROR = "matching_error"
    WAITING_FOR_DOCUMENTS = "waiting_for_documents"


class CaseActionType(StrEnum):
    CREATED = "created"
    CLAIMED = "claimed"
    REASSIGNED = "reassigned"
    RESOLUTION_CHANGED = "resolution_changed"
    SUBMITTED_FOR_APPROVAL = "submitted_for_approval"
    SUBMITTED_FOR_VOID = "submitted_for_void"
    RETURNED = "returned"
    APPROVED = "approved"
    VOIDED = "voided"


class AssignmentFilter(StrEnum):
    ALL = "all"
    MINE = "mine"
    UNASSIGNED = "unassigned"


class ReconciliationCase(BaseModel):
    case_id: str
    reconciliation_id: str
    status: CaseStatus
    assignee_user_id: str | None = None
    revision: int = Field(ge=1)
    created_by: str
    created_at: datetime
    claimed_at: datetime | None = None
    submitted_at: datetime | None = None
    completed_at: datetime | None = None


class CaseItem(BaseModel):
    item_id: str
    case_id: str
    item_type: CaseItemType
    line_result_id: str | None = None
    resolution_type: ResolutionType | None = None
    resolution_note: str | None = None
    resolved_by: str | None = None
    resolved_at: datetime | None = None
    updated_at: datetime

    @field_validator("resolution_note")
    @classmethod
    def resolution_note_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("resolution_note must not be blank")
        return value


class CaseAction(BaseModel):
    action_id: str
    case_id: str
    item_id: str | None = None
    actor_user_id: str
    action: CaseActionType
    old_value: object | None = None
    new_value: object | None = None
    reason: str | None = None
    created_at: datetime


class ReconciliationCaseBundle(BaseModel):
    case: ReconciliationCase
    items: list[CaseItem]
    actions: list[CaseAction]


class CaseSummary(BaseModel):
    case: ReconciliationCase
    invoice_number: str
    receive_note_numbers: list[str]
    actionable_count: int
    assignee_username: str | None = None


class CaseActionView(BaseModel):
    action: CaseAction
    actor_username: str


class CaseDetail(BaseModel):
    case: ReconciliationCase
    items: list[CaseItem]
    actions: list[CaseActionView]
    reconciliation: ReconciliationRecord


class CaseListQuery(BaseModel):
    statuses: tuple[CaseStatus, ...] = ()
    assignment: AssignmentFilter = AssignmentFilter.ALL
    invoice_number: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=100)


class CasePage(BaseModel):
    items: list[CaseSummary]
    page: int
    page_size: int
    total: int
