from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import get_extraction_service
from app.domain.extraction_runs import ExtractionRun
from app.services.document_upload_service import ExtractionTaskNotFound
from app.services.extraction_service import (
    ExtractionRunNotFound,
    ExtractionService,
    ExtractionStateConflict,
)

router = APIRouter(prefix="/api", tags=["document extraction"])


@router.post(
    "/extraction-tasks/{task_id}/extract",
    response_model=ExtractionRun,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_extraction(
    task_id: str,
    service: ExtractionService = Depends(get_extraction_service),
) -> ExtractionRun:
    try:
        run = service.queue(task_id)
    except ExtractionTaskNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Extraction task not found",
        ) from exc
    except ExtractionStateConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    return run


@router.get("/extraction-runs/{run_id}", response_model=ExtractionRun)
def get_extraction_run(
    run_id: str,
    service: ExtractionService = Depends(get_extraction_service),
) -> ExtractionRun:
    try:
        return service.get_run(run_id)
    except ExtractionRunNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Extraction run not found",
        ) from exc
