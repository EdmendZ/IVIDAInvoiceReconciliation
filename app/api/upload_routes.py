"""文件上传、Task 列表和 Task 查询端点。"""

from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)

from app.api.auth_dependencies import require_reviewer
from app.api.dependencies import (
    get_document_upload_service,
    get_run_repository,
)
from app.domain.admin_users import AuthenticatedUser
from app.services.ports import ExtractionRunRepository
from app.core.config import get_settings
from app.domain.documents import DocumentType
from app.domain.extraction_tasks import ExtractionTask
from app.services.document_upload_service import (
    DocumentUploadService,
    DocumentValidationError,
    ExtractionTaskNotFound,
)

router = APIRouter(prefix="/api", tags=["document extraction"])


@router.get("/extraction-tasks")
def list_extraction_tasks(
    limit: int = Query(default=50, ge=1, le=200),
    service: DocumentUploadService = Depends(get_document_upload_service),
    run_repository: ExtractionRunRepository = Depends(get_run_repository),
    user: AuthenticatedUser = Depends(require_reviewer),
) -> list[dict]:
    """返回最近 Task，并组合每个 Task 的最新 Run 供 UI 展示。"""

    del user
    result: list[dict] = []
    for task in service.list_tasks(limit):
        run = run_repository.get_latest_for_task(task.task_id)
        result.append(
            {
                "task": task.model_dump(mode="json"),
                "latest_run": run.model_dump(mode="json") if run else None,
            }
        )
    return result


@router.post(
    "/documents/upload",
    response_model=ExtractionTask,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    document_type: Annotated[DocumentType, Form()],
    file: Annotated[UploadFile, File()],
    purchase_order_hint: Annotated[str | None, Form()] = None,
    service: DocumentUploadService = Depends(get_document_upload_service),
    user: AuthenticatedUser = Depends(require_reviewer),
) -> ExtractionTask:
    """限制读取大小后交给上传信任边界验证和持久化。"""

    del user
    max_bytes = get_settings().upload_max_bytes
    # 多读 1 byte 才能区分“刚好达到上限”和“超过上限”。
    data = await file.read(max_bytes + 1)
    try:
        return service.upload(
            document_type=document_type,
            filename=file.filename or "",
            data=data,
            purchase_order_hint=purchase_order_hint,
        )
    except DocumentValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Document storage is temporarily unavailable",
        ) from exc
    finally:
        await file.close()


@router.get("/extraction-tasks/{task_id}", response_model=ExtractionTask)
def get_extraction_task(
    task_id: str,
    service: DocumentUploadService = Depends(get_document_upload_service),
    user: AuthenticatedUser = Depends(require_reviewer),
) -> ExtractionTask:
    """按 ID 返回文件级 Task，不混入每次 Run 的细节。"""

    del user
    try:
        return service.get_task(task_id)
    except ExtractionTaskNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Extraction task not found",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Task storage is temporarily unavailable",
        ) from exc
