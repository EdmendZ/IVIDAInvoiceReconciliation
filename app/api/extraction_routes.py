from fastapi import APIRouter, Depends, HTTPException, status

from app.api.auth_dependencies import require_reviewer
from app.api.dependencies import (
    get_draft_repository,
    get_extraction_service,
    get_parse_repository,
)
from app.domain.admin_users import AuthenticatedUser
from app.domain.extraction_runs import ExtractionRun
from app.services.document_upload_service import ExtractionTaskNotFound
from app.services.extraction_service import (
    ExtractionRunNotFound,
    ExtractionService,
    ExtractionStateConflict,
)
from app.services.ports import DocumentDraftRepository, ParseResultRepository

router = APIRouter(prefix="/api", tags=["document extraction"])


@router.post(
    "/extraction-tasks/{task_id}/extract",
    response_model=ExtractionRun,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_extraction(
    task_id: str,
    service: ExtractionService = Depends(get_extraction_service),
    user: AuthenticatedUser = Depends(require_reviewer),
) -> ExtractionRun:
    del user
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
    user: AuthenticatedUser = Depends(require_reviewer),
) -> ExtractionRun:
    del user
    try:
        return service.get_run(run_id)
    except ExtractionRunNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Extraction run not found",
        ) from exc


@router.get("/extraction-runs/{run_id}/result")
def get_extraction_result(
    run_id: str,
    service: ExtractionService = Depends(get_extraction_service),
    parse_repository: ParseResultRepository = Depends(get_parse_repository),
    draft_repository: DocumentDraftRepository = Depends(get_draft_repository),
    user: AuthenticatedUser = Depends(require_reviewer),
) -> dict:
    del user
    try:
        run = service.get_run(run_id)
    except ExtractionRunNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Extraction run not found",
        ) from exc
    parse = parse_repository.get_for_run(run_id)
    bundle = draft_repository.get_for_run(run_id)
    return {
        "run": run.model_dump(mode="json"),
        "parse": parse.model_dump(mode="json") if parse else None,
        "draft": bundle.draft.normalized_json if bundle else None,
        "validation_state": (
            bundle.draft.validation_state.value if bundle else None
        ),
        "evidence": (
            [item.model_dump(mode="json") for item in bundle.evidence]
            if bundle
            else []
        ),
        "issues": (
            [item.model_dump(mode="json") for item in bundle.issues]
            if bundle
            else []
        ),
        "approval_allowed": False,
    }
