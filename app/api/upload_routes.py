from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.api.dependencies import get_document_upload_service
from app.core.config import get_settings
from app.domain.documents import DocumentType
from app.domain.extraction_tasks import ExtractionTask
from app.services.document_upload_service import (
    DocumentUploadService,
    DocumentValidationError,
    ExtractionTaskNotFound,
)

router = APIRouter(prefix="/api", tags=["document extraction"])


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
) -> ExtractionTask:
    max_bytes = get_settings().upload_max_bytes
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
) -> ExtractionTask:
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

