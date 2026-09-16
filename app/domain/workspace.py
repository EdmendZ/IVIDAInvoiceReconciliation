"""Workspace wire and persistence contracts; no business or storage implementation."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal, Union
from uuid import UUID

from pydantic import (AfterValidator, BaseModel, BeforeValidator, ConfigDict,
                      Discriminator, Field, StringConstraints, Tag, model_validator)

from app.domain.documents import DocumentType, Invoice, ReceiveNote
from app.domain.extraction_tasks import ExtractionTask
from app.domain.normalization import FieldEvidence
from app.domain.validation import ValidationIssue


def _uuid(value: str) -> str:
    return str(UUID(value))


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must have a timezone")
    return value.astimezone(timezone.utc)


def _no_float(value: object) -> object:
    if isinstance(value, float):
        raise ValueError("financial values must use Decimal or decimal strings")
    return value


def _unique(values: list) -> list:
    if len(values) != len(set(values)):
        raise ValueError("duplicate values are not allowed")
    return values


UUIDString = Annotated[str, AfterValidator(_uuid)]
UTCTimestamp = Annotated[datetime, AfterValidator(_utc)]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
NonemptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
FinancialDecimal = Annotated[Decimal, BeforeValidator(_no_float), Field(allow_inf_nan=False)]
PositiveInt = Annotated[int, Field(strict=True, ge=1)]
NonnegativeInt = Annotated[int, Field(strict=True, ge=0)]
UniqueIDs = Annotated[list[UUIDString], AfterValidator(_unique)]
UniqueDimensions = Annotated[list[str], AfterValidator(_unique)]


def _document_tag(value: object) -> str | None:
    if isinstance(value, dict):
        return value.get("document_type")
    return getattr(value, "document_type", None)


DocumentPayload = Annotated[
    Union[Annotated[Invoice, Tag("invoice")], Annotated[ReceiveNote, Tag("receive_note")]],
    Discriminator(_document_tag),
]


class WorkspaceDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProcessingStatus(StrEnum):
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"
    CANCELLED = "cancelled"
    VOIDED = "voided"


class MatchStatus(StrEnum):
    WAITING_COUNTERPART = "waiting_counterpart"
    NEEDS_SELECTION = "needs_selection"
    SELECTED = "selected"


class ReviewStatus(StrEnum):
    OPEN = "open"
    INVESTIGATING = "investigating"
    COMPLETED = "completed"


class DisplayStatus(StrEnum):
    PROCESSING = "processing"
    FAILED = "failed"
    CANCELLED = "cancelled"
    VOIDED = "voided"
    WAITING_COUNTERPART = "waiting_counterpart"
    NEEDS_ATTENTION = "needs_attention"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    COMPLETED = "completed"


class SourceKind(StrEnum):
    UPLOAD = "upload"
    TAPTOUCH = "taptouch"


class SelectionOrigin(StrEnum):
    AUTOMATIC = "automatic"
    MANUAL = "manual"


class RevisionOrigin(StrEnum):
    EXTRACTED = "extracted"
    MANUAL = "manual"
    UPSTREAM = "upstream"


class Resolution(StrEnum):
    MATCHED = "matched"
    RESOLVED_WITH_NOTE = "resolved_with_note"


class WorkspaceOperation(StrEnum):
    EDIT = "edit"
    SELECT = "select"
    INVESTIGATE = "investigate"
    CONFIRM = "confirm"
    REOPEN = "reopen"
    VOID = "void"
    RETRY = "retry"


class ActionType(StrEnum):
    UPLOADED = "uploaded"
    EXTRACTED = "extracted"
    EDITED = "edited"
    SELECTION_CHANGED = "selection_changed"
    INVESTIGATING = "investigating"
    CONFIRMED = "confirmed"
    REOPENED = "reopened"
    VOIDED = "voided"
    SOURCE_UPDATED = "source_updated"
    RETRY_REQUESTED = "retry_requested"


class MetricStatus(StrEnum):
    EQUAL = "equal"
    WITHIN_TOLERANCE = "within_tolerance"
    DIFFERENT = "different"
    UNVERIFIED = "unverified"


class LineStatus(StrEnum):
    EQUAL = "equal"
    WITHIN_TOLERANCE = "within_tolerance"
    DIFFERENT = "different"
    UNVERIFIED = "unverified"
    INVOICE_ONLY = "invoice_only"
    RECEIVE_ONLY = "receive_only"


class PreviewOutcome(StrEnum):
    CONSISTENT = "consistent"
    DIFFERENCE = "difference"
    BLOCKED = "blocked"


class Coverage(StrEnum):
    QUANTITY_ONLY = "quantity_only"
    QUANTITY_AND_PRICE = "quantity_and_price"
    QUANTITY_AND_AMOUNT = "quantity_and_amount"
    FULL = "full"


class BlockingCode(StrEnum):
    EMPTY_ITEM_KEY = "EMPTY_ITEM_KEY"
    UNIT_UNVERIFIED = "UNIT_UNVERIFIED"
    UNIT_CONFLICT = "UNIT_CONFLICT"
    SUPPLIER_UNVERIFIED = "SUPPLIER_UNVERIFIED"
    SUPPLIER_CONFLICT = "SUPPLIER_CONFLICT"
    CURRENCY_CONFLICT = "CURRENCY_CONFLICT"
    UNSUPPORTED_CURRENCY = "UNSUPPORTED_CURRENCY"
    SOURCE_VOIDED = "SOURCE_VOIDED"
    VALIDATION_BLOCKED = "VALIDATION_BLOCKED"
    DUPLICATE_INVOICE = "DUPLICATE_INVOICE"
    RECEIVING_IN_USE = "RECEIVING_IN_USE"


class CandidateReasonCode(StrEnum):
    PO_MATCH = "PO_MATCH"
    PO_CONFLICT = "PO_CONFLICT"
    SUPPLIER_MATCH = "SUPPLIER_MATCH"
    SUPPLIER_UNVERIFIED = "SUPPLIER_UNVERIFIED"
    SUPPLIER_CONFLICT = "SUPPLIER_CONFLICT"
    CURRENCY_MATCH = "CURRENCY_MATCH"
    CURRENCY_CONFLICT = "CURRENCY_CONFLICT"
    DATE_NEAR = "DATE_NEAR"
    DATE_MISSING = "DATE_MISSING"
    DATE_OUTSIDE_WINDOW = "DATE_OUTSIDE_WINDOW"
    ITEM_OVERLAP = "ITEM_OVERLAP"
    NO_ITEM_OVERLAP = "NO_ITEM_OVERLAP"
    RECEIVING_IN_USE = "RECEIVING_IN_USE"
    SOURCE_VOIDED = "SOURCE_VOIDED"


class WorkspaceErrorCode(StrEnum):
    INVALID_REQUEST = "INVALID_REQUEST"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    FORBIDDEN = "FORBIDDEN"
    DOCUMENT_NOT_FOUND = "DOCUMENT_NOT_FOUND"
    REVISION_CONFLICT = "REVISION_CONFLICT"
    PREVIEW_STALE = "PREVIEW_STALE"
    SOURCE_REVIEW_REQUIRED = "SOURCE_REVIEW_REQUIRED"
    SOURCE_VOIDED = "SOURCE_VOIDED"
    RECEIVING_IN_USE = "RECEIVING_IN_USE"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    INVALID_TRANSITION = "INVALID_TRANSITION"
    LEGACY_READ_ONLY = "LEGACY_READ_ONLY"
    VALIDATION_BLOCKED = "VALIDATION_BLOCKED"
    UNRESOLVED_MATCH = "UNRESOLVED_MATCH"
    UNVERIFIED_NOT_ACKNOWLEDGED = "UNVERIFIED_NOT_ACKNOWLEDGED"
    RESOLUTION_NOTE_REQUIRED = "RESOLUTION_NOTE_REQUIRED"
    SUBJECT_CONFLICT = "SUBJECT_CONFLICT"
    PARTIAL_ALLOCATION_UNSUPPORTED = "PARTIAL_ALLOCATION_UNSUPPORTED"
    DUPLICATE_INVOICE = "DUPLICATE_INVOICE"
    INVALID_FILE = "INVALID_FILE"
    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"
    WORKSPACE_UNAVAILABLE = "WORKSPACE_UNAVAILABLE"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class WorkspaceErrorDetail(WorkspaceDTO):
    code: WorkspaceErrorCode
    message: str
    document_id: UUIDString | None = None
    current_revision: PositiveInt | None = None


class WorkspaceErrorResponse(WorkspaceDTO):
    detail: WorkspaceErrorDetail


class WorkspaceError(Exception):
    """Domain failure; the HTTP adapter serializes detail excluding None values."""

    def __init__(self, code: WorkspaceErrorCode, message: str, *,
                 document_id: str | None = None, current_revision: int | None = None):
        self.detail = WorkspaceErrorDetail(code=code, message=message,
                                          document_id=document_id, current_revision=current_revision)
        super().__init__(message)


class WorkspaceScopeKey(WorkspaceDTO):
    tenant_id: NonemptyText
    store_id: NonemptyText

    @property
    def scope_id(self) -> str:
        return json.dumps([self.tenant_id, self.store_id], ensure_ascii=False, separators=(",", ":"))


class Tolerances(WorkspaceDTO):
    quantity: FinancialDecimal = Decimal("0")
    unit_price: FinancialDecimal = Decimal("0.01")
    amount: FinancialDecimal = Decimal("0.02")

    @model_validator(mode="after")
    def fixed_values(self):
        if (self.quantity, self.unit_price, self.amount) != (Decimal("0"), Decimal("0.01"), Decimal("0.02")):
            raise ValueError("ir-simple-rules-1 tolerances are fixed")
        return self


class MetricComparison(WorkspaceDTO):
    invoice_value: FinancialDecimal | None = None
    received_value: FinancialDecimal | None = None
    difference: FinancialDecimal | None = None
    status: MetricStatus
    reason_code: str | None = None


class ReceiveLineReference(WorkspaceDTO):
    document_id: UUIDString
    line_index: NonnegativeInt


class LineResult(WorkspaceDTO):
    match_key: str
    sku: str | None = None
    description: str
    invoice_unit: str | None = None
    received_unit: str | None = None
    quantity: MetricComparison
    price: MetricComparison
    amount: MetricComparison
    status: LineStatus
    reason_codes: list[str] = Field(default_factory=list)
    invoice_line_indexes: list[NonnegativeInt] = Field(default_factory=list)
    receive_lines: list[ReceiveLineReference] = Field(default_factory=list)


class PreviewSummary(WorkspaceDTO):
    total_lines: NonnegativeInt
    different_lines: NonnegativeInt
    unverified_lines: NonnegativeInt


class SubjectComparison(WorkspaceDTO):
    supplier: Literal["equal", "unverified", "conflict"]
    currency: Literal["equal", "conflict"]
    scope: Literal["equal"] = "equal"


class PreviewResult(WorkspaceDTO):
    outcome: PreviewOutcome
    coverage: Coverage
    blocking_codes: list[BlockingCode] = Field(default_factory=list)
    unverified_dimensions: UniqueDimensions = Field(default_factory=lambda: ["document_total", "tax"])
    lines: list[LineResult] = Field(default_factory=list)
    summary: PreviewSummary
    subject: SubjectComparison

    @model_validator(mode="after")
    def required_unverified_dimensions(self):
        if not {"document_total", "tax"}.issubset(self.unverified_dimensions):
            raise ValueError("document_total and tax remain unverified")
        return self


class RevisionView(WorkspaceDTO):
    revision_id: UUIDString
    document_id: UUIDString
    sequence: PositiveInt
    origin: RevisionOrigin
    payload: DocumentPayload
    evidence: list[FieldEvidence] = Field(default_factory=list)
    validation_issues: list[ValidationIssue] = Field(default_factory=list)
    evidence_origin_revision_id: UUIDString | None = None
    created_at: UTCTimestamp


class Candidate(WorkspaceDTO):
    document_id: UUIDString
    revision_id: UUIDString
    document_number: str
    score: Annotated[int, Field(strict=True, ge=0, le=100)]
    eligible: bool
    reason_codes: list[CandidateReasonCode] = Field(default_factory=list)
    source_kind: SourceKind
    supplier_name: str | None = None
    document_date: date | None = None
    already_used: bool


class MatchProposal(WorkspaceDTO):
    status: MatchStatus
    candidates: list[Candidate] = Field(default_factory=list)
    selected_document_ids: UniqueIDs = Field(default_factory=list)


class PreviewView(WorkspaceDTO):
    preview_id: UUIDString
    input_revision_ids: UniqueIDs
    scope_generation: NonnegativeInt
    rule_version: Literal["ir-simple-rules-1"] = "ir-simple-rules-1"
    tolerances: Tolerances = Field(default_factory=Tolerances)
    input_sha256: str
    result: PreviewResult
    created_at: UTCTimestamp


class ConfirmationView(WorkspaceDTO):
    confirmation_id: UUIDString
    preview_id: UUIDString
    resolution: Resolution
    note: Reason | None = None
    acknowledged_unverified_dimensions: UniqueDimensions
    result_snapshot: PreviewResult
    rule_version: Literal["ir-simple-rules-1"] = "ir-simple-rules-1"
    tolerances: Tolerances = Field(default_factory=Tolerances)
    input_revision_ids: UniqueIDs
    actor_id: UUIDString
    created_at: UTCTimestamp


class ActionView(WorkspaceDTO):
    action_id: UUIDString
    action: ActionType
    actor_id: UUIDString | None = None
    reason: Reason | None = None
    old_revision: PositiveInt | None = None
    new_revision: PositiveInt
    confirmation_id: UUIDString | None = None
    created_at: UTCTimestamp


class DocumentSummary(WorkspaceDTO):
    document_id: UUIDString
    document_type: DocumentType
    source_kind: SourceKind
    revision: PositiveInt
    processing_status: ProcessingStatus
    display_status: DisplayStatus
    document_number: str | None = None
    supplier_name: str | None = None
    document_date: date | None = None
    selected_document_ids: UniqueIDs = Field(default_factory=list)
    source_changed: bool = False
    updated_at: UTCTimestamp
    error_code: str | None = None


class DocumentDetail(WorkspaceDTO):
    document: DocumentSummary
    review_status: ReviewStatus | None = None
    match_status: MatchStatus
    selection_origin: SelectionOrigin | None = None
    selection_note: Reason | None = None
    current_revision: RevisionView | None = None
    candidates: list[Candidate] = Field(default_factory=list)
    selected_receivings: list[RevisionView] = Field(default_factory=list)
    preview: PreviewView | None = None
    preview_stale: bool
    confirmation: ConfirmationView | None = None
    actions: list[ActionView] = Field(default_factory=list, max_length=50)
    source_url_available: bool


class PageQuery(WorkspaceDTO):
    page: PositiveInt = 1
    page_size: Annotated[int, Field(strict=True, ge=1, le=100)] = 20


class DocumentQuery(PageQuery):
    type: DocumentType = DocumentType.INVOICE
    status: list[DisplayStatus] = Field(default_factory=list)
    q: Annotated[str, Field(max_length=100)] | None = None


class DocumentPage(PageQuery):
    items: list[DocumentSummary] = Field(default_factory=list)
    total: NonnegativeInt


class ActionPage(PageQuery):
    items: list[ActionView] = Field(default_factory=list)
    total: NonnegativeInt


class UploadCommand(WorkspaceDTO):
    document_type: DocumentType
    filename: str
    data: bytes


class RevisionCommand(WorkspaceDTO):
    expected_revision: PositiveInt


class ReasonCommand(RevisionCommand):
    reason: Reason


class EditCommand(ReasonCommand):
    document: DocumentPayload


class SelectionCommand(ReasonCommand):
    receive_document_ids: Annotated[UniqueIDs, Field(max_length=100)]


class InvestigateCommand(RevisionCommand):
    note: Reason


class ConfirmCommand(RevisionCommand):
    preview_id: UUIDString
    acknowledged_sources: Annotated[bool, Field(strict=True)]
    acknowledged_unverified_dimensions: UniqueDimensions
    resolution: Resolution
    note: Reason | None = None

    @model_validator(mode="after")
    def require_acknowledgement_and_note(self):
        if not self.acknowledged_sources:
            raise ValueError("acknowledged_sources must be true")
        if self.resolution == Resolution.RESOLVED_WITH_NOTE and self.note is None:
            raise ValueError("resolved_with_note requires a note")
        return self


WorkspaceCommand = EditCommand | SelectionCommand | InvestigateCommand | ConfirmCommand | ReasonCommand | RevisionCommand


class IntakeResponse(WorkspaceDTO):
    document: DocumentSummary
    task_id: UUIDString
    run_id: UUIDString
    duplicate: bool


class ConfirmationResponse(WorkspaceDTO):
    document: DocumentSummary
    confirmation: ConfirmationView


class RetryResponse(WorkspaceDTO):
    document: DocumentSummary
    run_id: UUIDString


WorkspaceMutationResponse = DocumentSummary | ConfirmationResponse | RetryResponse


class PreparedUpload(WorkspaceDTO):
    task: ExtractionTask


class SourceMetadata(WorkspaceDTO):
    filename: str
    content_type: str
    object_key: str


class SourceFile(WorkspaceDTO):
    filename: str
    content_type: str
    data: bytes


class RuntimeView(WorkspaceDTO):
    enabled: bool
    worker_online: bool
    last_sync_at: UTCTimestamp | None = None
    preview_lag_seconds: NonnegativeInt | None = None


class CachedResponse(WorkspaceDTO):
    status: int
    body: dict


class SyncSummary(WorkspaceDTO):
    changed_documents: NonnegativeInt
    scope_generation: NonnegativeInt


class PreviewInput(WorkspaceDTO):
    invoice: RevisionView
    receivings: list[RevisionView]
    used_ids: set[UUIDString]
    scope_generation: NonnegativeInt
    document_revision: PositiveInt
    manual_selection_ids: Annotated[UniqueIDs, Field(min_length=1, max_length=100)] | None = None


class TickSummary(WorkspaceDTO):
    synced: NonnegativeInt
    previews_saved: NonnegativeInt
    previews_discarded: NonnegativeInt
    errors: NonnegativeInt


class WorkspaceDocument(WorkspaceDTO):
    document_id: UUIDString
    tenant_id: NonemptyText
    store_id: NonemptyText
    document_type: DocumentType
    source_kind: SourceKind
    task_id: UUIDString | None = None
    upstream_identity: str | None = None
    current_revision_id: UUIDString | None = None
    revision: PositiveInt = 1
    processing_status: ProcessingStatus = ProcessingStatus.PROCESSING
    review_status: ReviewStatus | None = None
    selected_document_ids: UniqueIDs = Field(default_factory=list)
    selection_origin: SelectionOrigin | None = None
    selection_note: Reason | None = None
    match_status: MatchStatus = MatchStatus.WAITING_COUNTERPART
    current_preview_id: UUIDString | None = None
    preview_stale: bool = True
    current_confirmation_id: UUIDString | None = None
    source_changed: bool = False
    error_code: str | None = None
    created_by: UUIDString | None = None
    created_at: UTCTimestamp
    updated_at: UTCTimestamp

    @model_validator(mode="after")
    def record_shape(self):
        if self.source_kind == SourceKind.UPLOAD and self.task_id is None:
            raise ValueError("upload requires task_id")
        if self.source_kind == SourceKind.TAPTOUCH:
            try:
                identity = json.loads(self.upstream_identity or "")
            except ValueError as exc:
                raise ValueError("upstream_identity must be canonical JSON") from exc
            if (not isinstance(identity, list) or len(identity) != 4
                    or any(not isinstance(item, str) or not item for item in identity)
                    or json.dumps(identity, ensure_ascii=False, separators=(",", ":")) != self.upstream_identity):
                raise ValueError("upstream_identity must be a canonical four-string array")
        if (self.document_type == DocumentType.INVOICE) != (self.review_status is not None):
            raise ValueError("review_status is required only for invoice")
        if self.processing_status == ProcessingStatus.READY and self.current_revision_id is None:
            raise ValueError("ready requires current_revision_id")
        if self.selected_document_ids != sorted(self.selected_document_ids):
            raise ValueError("selected_document_ids must be sorted")
        if self.selection_origin == SelectionOrigin.MANUAL and (not self.selected_document_ids or self.selection_note is None):
            raise ValueError("manual selection requires IDs and a reason")
        return self


class WorkspaceRevision(RevisionView):
    source_draft_id: UUIDString | None = None
    source_version_id: UUIDString | None = None
    content_sha256: str
    actor_id: UUIDString | None = None
    reason: Reason | None = None

    @model_validator(mode="after")
    def source_reference(self):
        if self.source_draft_id is not None and self.source_version_id is not None:
            raise ValueError("at most one source reference is allowed")
        if self.origin == RevisionOrigin.EXTRACTED and self.source_draft_id is None:
            raise ValueError("extracted revision requires source_draft_id")
        if self.origin == RevisionOrigin.UPSTREAM and self.source_version_id is None:
            raise ValueError("upstream revision requires source_version_id")
        return self


class WorkspacePreview(PreviewView):
    invoice_document_id: UUIDString
    selection_origin: SelectionOrigin


class WorkspaceConfirmation(WorkspaceDTO):
    confirmation_id: UUIDString
    invoice_document_id: UUIDString
    preview_id: UUIDString
    invoice_revision_id: UUIDString
    receive_revision_ids: UniqueIDs
    result_snapshot: PreviewResult
    rule_version: Literal["ir-simple-rules-1"] = "ir-simple-rules-1"
    tolerances: Tolerances = Field(default_factory=Tolerances)
    input_sha256: str
    actor_id: UUIDString
    resolution: Resolution
    note: Reason | None = None
    acknowledged_unverified_dimensions: UniqueDimensions
    created_at: UTCTimestamp


class WorkspaceClaim(WorkspaceDTO):
    receive_document_id: UUIDString
    invoice_document_id: UUIDString
    confirmation_id: UUIDString
    created_at: UTCTimestamp


class WorkspaceAction(ActionView):
    document_id: UUIDString


class WorkspaceScope(WorkspaceDTO):
    scope_id: str
    generation: NonnegativeInt = 0
    last_sync_at: UTCTimestamp | None = None
    last_error_code: str | None = None
    updated_at: UTCTimestamp


class WorkspaceRequest(WorkspaceDTO):
    scope_id: str
    actor_id: UUIDString
    idempotency_key: UUIDString
    request_hash: str
    response_status: Annotated[int, Field(ge=200, le=299)]
    response_json: dict
    created_at: UTCTimestamp
