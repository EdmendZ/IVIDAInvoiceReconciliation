"""Authenticated HTTP contract for reconciliation exception cases."""

from collections.abc import Callable
from typing import Annotated, TypeVar

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from app.api.auth_dependencies import require_reviewer
from app.api.dependencies import (
    get_admin_repository,
    get_reconciliation_case_service,
)
from app.domain.admin_users import AdminRole, AuthenticatedUser
from app.domain.reconciliation_cases import (
    AssignmentFilter,
    CaseDetail,
    CaseListQuery,
    CasePage,
    CaseStatus,
    ResolutionType,
)
from app.infra.postgres_admin_repository import PostgresAdminRepository
from app.services.reconciliation_case_service import (
    CaseError,
    ReconciliationCaseService,
)


router = APIRouter(prefix="/api/reconciliation-cases", tags=["reconciliation cases"])
T = TypeVar("T")


class RevisionRequest(BaseModel):
    expected_revision: int = Field(ge=1)


class ResolutionRequest(RevisionRequest):
    resolution_type: ResolutionType
    note: str = Field(min_length=1)

    @field_validator("note")
    @classmethod
    def note_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("note must not be blank")
        return value


class ReassignRequest(RevisionRequest):
    assignee_user_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)

    @field_validator("assignee_user_id", "reason")
    @classmethod
    def required_text_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must not be blank")
        return value


class ReturnRequest(RevisionRequest):
    reason: str = Field(min_length=1)

    @field_validator("reason")
    @classmethod
    def reason_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("reason must not be blank")
        return value


class AssigneeResponse(BaseModel):
    user_id: str
    username: str


def case_http_error(error: CaseError) -> HTTPException:
    """Translate stable domain codes without exposing implementation details."""

    status_code = 404 if error.code == "CASE_NOT_FOUND" else (
        403
        if error.code in {"CASE_ASSIGNEE_REQUIRED", "CASE_ADMIN_REQUIRED"}
        else 409
    )
    return HTTPException(
        status_code=status_code,
        detail={"code": error.code, "message": error.message},
    )


def _case_call(operation: Callable[[], T]) -> T:
    try:
        return operation()
    except CaseError as error:
        raise case_http_error(error) from error


def _mutate_and_read(
    operation: Callable[[], object],
    *,
    case_id: str,
    service: ReconciliationCaseService,
) -> CaseDetail:
    def run() -> CaseDetail:
        operation()
        return service.get_detail(case_id)

    return _case_call(run)


@router.get("", response_model=CasePage)
def list_cases(
    status: Annotated[list[CaseStatus] | None, Query()] = None,
    assignment: AssignmentFilter = AssignmentFilter.ALL,
    invoice_number: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    service: ReconciliationCaseService = Depends(get_reconciliation_case_service),
    user: AuthenticatedUser = Depends(require_reviewer),
) -> CasePage:
    """List cases using stable oldest-first pagination and authenticated ownership."""

    query = CaseListQuery(
        statuses=tuple(status or ()),
        assignment=assignment,
        invoice_number=invoice_number,
        page=page,
        page_size=page_size,
    )
    return _case_call(lambda: service.list_cases(query, user=user))


@router.get("/assignees", response_model=list[AssigneeResponse])
def list_assignees(
    repository: PostgresAdminRepository = Depends(get_admin_repository),
    user: AuthenticatedUser = Depends(require_reviewer),
) -> list[AssigneeResponse]:
    """Return only active Reviewer identities and only to Admin users."""

    if user.role != AdminRole.ADMIN:
        raise case_http_error(CaseError("CASE_ADMIN_REQUIRED", "Admin role required"))
    return [
        AssigneeResponse(user_id=reviewer.user_id, username=reviewer.username)
        for reviewer in repository.list_active_reviewers()
    ]


@router.get("/{case_id}", response_model=CaseDetail)
def get_case_detail(
    case_id: str,
    service: ReconciliationCaseService = Depends(get_reconciliation_case_service),
    user: AuthenticatedUser = Depends(require_reviewer),
) -> CaseDetail:
    """Return immutable reconciliation data, current items, and audit history."""

    del user
    return _case_call(lambda: service.get_detail(case_id))


@router.post("/{case_id}/claim", response_model=CaseDetail)
def claim_case(
    case_id: str,
    request: RevisionRequest,
    service: ReconciliationCaseService = Depends(get_reconciliation_case_service),
    user: AuthenticatedUser = Depends(require_reviewer),
) -> CaseDetail:
    return _mutate_and_read(
        lambda: service.claim(
            case_id,
            user=user,
            expected_revision=request.expected_revision,
        ),
        case_id=case_id,
        service=service,
    )


@router.post("/{case_id}/reassign", response_model=CaseDetail)
def reassign_case(
    case_id: str,
    request: ReassignRequest,
    service: ReconciliationCaseService = Depends(get_reconciliation_case_service),
    user: AuthenticatedUser = Depends(require_reviewer),
) -> CaseDetail:
    return _mutate_and_read(
        lambda: service.reassign(
            case_id,
            request.assignee_user_id,
            user=user,
            reason=request.reason,
            expected_revision=request.expected_revision,
        ),
        case_id=case_id,
        service=service,
    )


@router.put("/{case_id}/items/{item_id}/resolution", response_model=CaseDetail)
def update_resolution(
    case_id: str,
    item_id: str,
    request: ResolutionRequest,
    service: ReconciliationCaseService = Depends(get_reconciliation_case_service),
    user: AuthenticatedUser = Depends(require_reviewer),
) -> CaseDetail:
    return _mutate_and_read(
        lambda: service.set_resolution(
            case_id,
            item_id,
            request.resolution_type,
            request.note,
            user=user,
            expected_revision=request.expected_revision,
        ),
        case_id=case_id,
        service=service,
    )


@router.post("/{case_id}/submit-approval", response_model=CaseDetail)
def submit_approval(
    case_id: str,
    request: RevisionRequest,
    service: ReconciliationCaseService = Depends(get_reconciliation_case_service),
    user: AuthenticatedUser = Depends(require_reviewer),
) -> CaseDetail:
    return _mutate_and_read(
        lambda: service.submit_approval(
            case_id,
            user=user,
            expected_revision=request.expected_revision,
        ),
        case_id=case_id,
        service=service,
    )


@router.post("/{case_id}/submit-void", response_model=CaseDetail)
def submit_void(
    case_id: str,
    request: RevisionRequest,
    service: ReconciliationCaseService = Depends(get_reconciliation_case_service),
    user: AuthenticatedUser = Depends(require_reviewer),
) -> CaseDetail:
    return _mutate_and_read(
        lambda: service.submit_void(
            case_id,
            user=user,
            expected_revision=request.expected_revision,
        ),
        case_id=case_id,
        service=service,
    )


@router.post("/{case_id}/approve", response_model=CaseDetail)
def approve_case(
    case_id: str,
    request: RevisionRequest,
    service: ReconciliationCaseService = Depends(get_reconciliation_case_service),
    user: AuthenticatedUser = Depends(require_reviewer),
) -> CaseDetail:
    return _mutate_and_read(
        lambda: service.approve(
            case_id,
            user=user,
            expected_revision=request.expected_revision,
        ),
        case_id=case_id,
        service=service,
    )


@router.post("/{case_id}/return", response_model=CaseDetail)
def return_case(
    case_id: str,
    request: ReturnRequest,
    service: ReconciliationCaseService = Depends(get_reconciliation_case_service),
    user: AuthenticatedUser = Depends(require_reviewer),
) -> CaseDetail:
    return _mutate_and_read(
        lambda: service.return_case(
            case_id,
            user=user,
            reason=request.reason,
            expected_revision=request.expected_revision,
        ),
        case_id=case_id,
        service=service,
    )


@router.post("/{case_id}/void", response_model=CaseDetail)
def void_case(
    case_id: str,
    request: RevisionRequest,
    service: ReconciliationCaseService = Depends(get_reconciliation_case_service),
    user: AuthenticatedUser = Depends(require_reviewer),
) -> CaseDetail:
    return _mutate_and_read(
        lambda: service.void(
            case_id,
            user=user,
            expected_revision=request.expected_revision,
        ),
        case_id=case_id,
        service=service,
    )
