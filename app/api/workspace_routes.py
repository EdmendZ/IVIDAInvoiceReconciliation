"""Authenticated HTTP adapter for the single-store reconciliation workspace."""

from __future__ import annotations

from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Path,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.exception_handlers import (
    http_exception_handler,
    request_validation_exception_handler,
)
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.exceptions import RequestValidationError

from app.api.auth_dependencies import require_reviewer
from app.api.dependencies import (
    get_workspace_runtime_service,
    get_workspace_service,
    require_workspace_writer,
)
from app.core.config import get_settings
from app.domain.admin_users import AuthenticatedUser
from app.domain.documents import DocumentType
from app.domain.workspace import (
    ActionPage,
    ConfirmationResponse,
    ConfirmationView,
    DisplayStatus,
    DocumentDetail,
    DocumentPage,
    DocumentQuery,
    DocumentSummary,
    EditCommand,
    InvestigateCommand,
    ConfirmCommand,
    IntakeResponse,
    ReasonCommand,
    RetryResponse,
    RevisionCommand,
    RuntimeView,
    SelectionCommand,
    UploadCommand,
    WorkspaceError,
    WorkspaceErrorCode,
)
from app.services.workspace_service import WorkspaceService


router = APIRouter(
    prefix="/api/workspace",
    tags=["reconciliation workspace"],
    dependencies=[Depends(require_reviewer)],
)

_ERROR_STATUS = {
    WorkspaceErrorCode.INVALID_REQUEST: status.HTTP_400_BAD_REQUEST,
    WorkspaceErrorCode.AUTH_REQUIRED: status.HTTP_401_UNAUTHORIZED,
    WorkspaceErrorCode.FORBIDDEN: status.HTTP_403_FORBIDDEN,
    WorkspaceErrorCode.DOCUMENT_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    WorkspaceErrorCode.REVISION_CONFLICT: status.HTTP_409_CONFLICT,
    WorkspaceErrorCode.PREVIEW_STALE: status.HTTP_409_CONFLICT,
    WorkspaceErrorCode.SOURCE_REVIEW_REQUIRED: status.HTTP_409_CONFLICT,
    WorkspaceErrorCode.SOURCE_VOIDED: status.HTTP_409_CONFLICT,
    WorkspaceErrorCode.RECEIVING_IN_USE: status.HTTP_409_CONFLICT,
    WorkspaceErrorCode.IDEMPOTENCY_CONFLICT: status.HTTP_409_CONFLICT,
    WorkspaceErrorCode.INVALID_TRANSITION: status.HTTP_409_CONFLICT,
    WorkspaceErrorCode.LEGACY_READ_ONLY: status.HTTP_409_CONFLICT,
    WorkspaceErrorCode.VALIDATION_BLOCKED: status.HTTP_422_UNPROCESSABLE_CONTENT,
    WorkspaceErrorCode.UNRESOLVED_MATCH: status.HTTP_422_UNPROCESSABLE_CONTENT,
    WorkspaceErrorCode.UNVERIFIED_NOT_ACKNOWLEDGED: status.HTTP_422_UNPROCESSABLE_CONTENT,
    WorkspaceErrorCode.RESOLUTION_NOTE_REQUIRED: status.HTTP_422_UNPROCESSABLE_CONTENT,
    WorkspaceErrorCode.SUBJECT_CONFLICT: status.HTTP_422_UNPROCESSABLE_CONTENT,
    WorkspaceErrorCode.PARTIAL_ALLOCATION_UNSUPPORTED: status.HTTP_422_UNPROCESSABLE_CONTENT,
    WorkspaceErrorCode.DUPLICATE_INVOICE: status.HTTP_422_UNPROCESSABLE_CONTENT,
    WorkspaceErrorCode.INVALID_FILE: status.HTTP_422_UNPROCESSABLE_CONTENT,
    WorkspaceErrorCode.STORAGE_UNAVAILABLE: status.HTTP_503_SERVICE_UNAVAILABLE,
    WorkspaceErrorCode.WORKSPACE_UNAVAILABLE: status.HTTP_503_SERVICE_UNAVAILABLE,
    WorkspaceErrorCode.INTERNAL_ERROR: status.HTTP_500_INTERNAL_SERVER_ERROR,
}


def _is_workspace_request(request: Request) -> bool:
    return request.url.path == "/api/workspace" or request.url.path.startswith(
        "/api/workspace/"
    )


def workspace_error_response(error: WorkspaceError) -> JSONResponse:
    """Serialize only the frozen, safe workspace error fields."""

    return JSONResponse(
        status_code=_ERROR_STATUS[error.detail.code],
        content={
            "detail": error.detail.model_dump(mode="json", exclude_none=True),
        },
    )


async def workspace_domain_exception_handler(
    request: Request, error: WorkspaceError
) -> Response:
    del request
    return workspace_error_response(error)


async def workspace_http_exception_handler(
    request: Request, error: HTTPException
) -> Response:
    if not _is_workspace_request(request):
        return await http_exception_handler(request, error)

    if isinstance(error.detail, dict) and {
        "code",
        "message",
    }.issubset(error.detail):
        detail = {
            key: error.detail[key]
            for key in ("code", "message", "document_id", "current_revision")
            if key in error.detail
        }
    elif error.status_code == status.HTTP_401_UNAUTHORIZED:
        detail = {"code": "AUTH_REQUIRED", "message": "请先登录后再访问工作台"}
    elif error.status_code == status.HTTP_403_FORBIDDEN:
        detail = {"code": "FORBIDDEN", "message": "当前账号无权访问工作台"}
    elif error.status_code == status.HTTP_404_NOT_FOUND:
        detail = {"code": "DOCUMENT_NOT_FOUND", "message": "未找到请求的记录"}
    else:
        detail = {"code": "INVALID_REQUEST", "message": "请求格式无效"}

    headers = dict(error.headers or {})
    if error.status_code == status.HTTP_401_UNAUTHORIZED:
        headers.setdefault("WWW-Authenticate", "Session")
    return JSONResponse(
        status_code=error.status_code,
        content={"detail": detail},
        headers=headers,
    )


async def workspace_validation_exception_handler(
    request: Request, error: RequestValidationError
) -> Response:
    if not _is_workspace_request(request):
        return await request_validation_exception_handler(request, error)
    errors = error.errors()
    body = error.body if isinstance(error.body, dict) else {}
    body_only = bool(errors) and all(
        item.get("loc", (None,))[0] == "body" for item in errors
    )
    if request.url.path.endswith("/confirm") and body_only:
        dimensions = body.get("acknowledged_unverified_dimensions")
        duplicate_dimensions = (
            isinstance(dimensions, list)
            and all(isinstance(item, str) for item in dimensions)
            and len(dimensions) != len(set(dimensions))
        )
        if body.get("acknowledged_sources") is not True or duplicate_dimensions:
            return JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                content={
                    "detail": {
                        "code": "UNVERIFIED_NOT_ACKNOWLEDGED",
                        "message": "请确认全部来源和未核验维度",
                    }
                },
            )
        note = body.get("note")
        if body.get("resolution") == "resolved_with_note" and (
            not isinstance(note, str)
            or not note.strip()
            or len(note.strip()) > 2000
        ):
            return JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                content={
                    "detail": {
                        "code": "RESOLUTION_NOTE_REQUIRED",
                        "message": "请按核对结果填写处理说明",
                    }
                },
            )
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "detail": {
                "code": "INVALID_REQUEST",
                "message": "请求参数格式不正确",
            }
        },
    )


IdempotencyKey = Annotated[UUID, Header(alias="Idempotency-Key")]
DocumentID = Annotated[UUID, Path(alias="id")]
ConfirmationID = Annotated[UUID, Path(alias="id")]


@router.post(
    "/documents",
    response_model=IntakeResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    request: Request,
    document_type: Annotated[DocumentType, Form()],
    file: Annotated[UploadFile, File()],
    idempotency_key: IdempotencyKey,
    actor: AuthenticatedUser = Depends(require_workspace_writer),
    service: WorkspaceService = Depends(get_workspace_service),
):
    """Validate a bounded upload and atomically enqueue its workspace intake."""

    form = await request.form()
    if set(form) != {"document_type", "file"}:
        raise WorkspaceError(
            WorkspaceErrorCode.INVALID_REQUEST,
            "上传请求只能包含文件和单据类型",
        )
    max_bytes = get_settings().upload_max_bytes
    data = await file.read(max_bytes + 1)
    try:
        return service.upload(
            UploadCommand(
                document_type=document_type,
                filename=file.filename or "",
                data=data,
            ),
            actor,
            str(idempotency_key),
        )
    finally:
        await file.close()


@router.get("/documents", response_model=DocumentPage)
def list_documents(
    document_type: Annotated[DocumentType, Query(alias="type")] = DocumentType.INVOICE,
    statuses: Annotated[list[DisplayStatus] | None, Query(alias="status")] = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    actor: AuthenticatedUser = Depends(require_reviewer),
    service: WorkspaceService = Depends(get_workspace_service),
) -> DocumentPage:
    del actor
    return service.list_documents(
        DocumentQuery(
            type=document_type,
            status=statuses or [],
            q=q,
            page=page,
            page_size=page_size,
        )
    )


@router.get("/documents/{id}", response_model=DocumentDetail)
def get_document(
    document_id: DocumentID,
    actor: AuthenticatedUser = Depends(require_reviewer),
    service: WorkspaceService = Depends(get_workspace_service),
) -> DocumentDetail:
    del actor
    return service.get_document(str(document_id))


@router.get("/documents/{id}/source")
def get_document_source(
    document_id: DocumentID,
    actor: AuthenticatedUser = Depends(require_reviewer),
    service: WorkspaceService = Depends(get_workspace_service),
) -> StreamingResponse:
    del actor
    source = service.source(str(document_id))
    ascii_name = quote(source.filename.encode("ascii", "ignore").decode() or "document")
    encoded_name = quote(source.filename, safe="")
    return StreamingResponse(
        iter((source.data,)),
        media_type=source.content_type,
        headers={
            "Content-Disposition": (
                f"inline; filename=\"{ascii_name}\"; filename*=UTF-8''{encoded_name}"
            ),
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/documents/{id}/actions", response_model=ActionPage)
def get_document_actions(
    document_id: DocumentID,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    actor: AuthenticatedUser = Depends(require_reviewer),
    service: WorkspaceService = Depends(get_workspace_service),
) -> ActionPage:
    del actor
    return service.get_actions(str(document_id), page, page_size)


@router.patch("/documents/{id}", response_model=DocumentSummary)
def edit_document(
    document_id: DocumentID,
    command: EditCommand,
    idempotency_key: IdempotencyKey,
    actor: AuthenticatedUser = Depends(require_workspace_writer),
    service: WorkspaceService = Depends(get_workspace_service),
) -> DocumentSummary:
    return service.edit(str(document_id), command, actor, str(idempotency_key))


@router.put("/documents/{id}/selection", response_model=DocumentSummary)
def select_receivings(
    document_id: DocumentID,
    command: SelectionCommand,
    idempotency_key: IdempotencyKey,
    actor: AuthenticatedUser = Depends(require_workspace_writer),
    service: WorkspaceService = Depends(get_workspace_service),
) -> DocumentSummary:
    return service.select(str(document_id), command, actor, str(idempotency_key))


@router.post("/documents/{id}/investigate", response_model=DocumentSummary)
def investigate_document(
    document_id: DocumentID,
    command: InvestigateCommand,
    idempotency_key: IdempotencyKey,
    actor: AuthenticatedUser = Depends(require_workspace_writer),
    service: WorkspaceService = Depends(get_workspace_service),
) -> DocumentSummary:
    return service.investigate(
        str(document_id), command, actor, str(idempotency_key)
    )


@router.post(
    "/documents/{id}/confirm",
    response_model=ConfirmationResponse,
    status_code=status.HTTP_201_CREATED,
)
def confirm_document(
    document_id: DocumentID,
    command: ConfirmCommand,
    idempotency_key: IdempotencyKey,
    actor: AuthenticatedUser = Depends(require_workspace_writer),
    service: WorkspaceService = Depends(get_workspace_service),
) -> ConfirmationResponse:
    return service.confirm(str(document_id), command, actor, str(idempotency_key))


@router.post("/documents/{id}/reopen", response_model=DocumentSummary)
def reopen_document(
    document_id: DocumentID,
    command: ReasonCommand,
    idempotency_key: IdempotencyKey,
    actor: AuthenticatedUser = Depends(require_workspace_writer),
    service: WorkspaceService = Depends(get_workspace_service),
) -> DocumentSummary:
    return service.reopen(str(document_id), command, actor, str(idempotency_key))


@router.post("/documents/{id}/void", response_model=DocumentSummary)
def void_document(
    document_id: DocumentID,
    command: ReasonCommand,
    idempotency_key: IdempotencyKey,
    actor: AuthenticatedUser = Depends(require_workspace_writer),
    service: WorkspaceService = Depends(get_workspace_service),
) -> DocumentSummary:
    return service.void(str(document_id), command, actor, str(idempotency_key))


@router.post(
    "/documents/{id}/retry",
    response_model=RetryResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def retry_document(
    document_id: DocumentID,
    command: RevisionCommand,
    idempotency_key: IdempotencyKey,
    actor: AuthenticatedUser = Depends(require_workspace_writer),
    service: WorkspaceService = Depends(get_workspace_service),
) -> RetryResponse:
    return service.retry(str(document_id), command, actor, str(idempotency_key))


@router.get("/confirmations/{id}", response_model=ConfirmationView)
def get_confirmation(
    confirmation_id: ConfirmationID,
    actor: AuthenticatedUser = Depends(require_reviewer),
    service: WorkspaceService = Depends(get_workspace_service),
) -> ConfirmationView:
    del actor
    return service.get_confirmation(str(confirmation_id))


@router.get("/confirmations/{id}/export.csv")
def export_confirmation(
    confirmation_id: ConfirmationID,
    actor: AuthenticatedUser = Depends(require_reviewer),
    service: WorkspaceService = Depends(get_workspace_service),
) -> Response:
    del actor
    content = service.export(str(confirmation_id))
    return Response(
        content=content.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="confirmation-{confirmation_id}.csv"'
            ),
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/runtime", response_model=RuntimeView)
def get_runtime(
    actor: AuthenticatedUser = Depends(require_reviewer),
    service: WorkspaceService | None = Depends(get_workspace_runtime_service),
) -> RuntimeView:
    del actor
    if service is None:
        return RuntimeView(
            enabled=False,
            worker_online=False,
            last_sync_at=None,
            preview_lag_seconds=None,
        )
    return service.runtime()
