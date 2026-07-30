from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.api.auth_dependencies import require_reviewer
from app.api.dependencies import get_review_service
from app.domain.admin_users import AuthenticatedUser
from app.domain.document_versions import DocumentVersionStatus
from app.domain.documents import DocumentType
from app.infra.postgres_review_repository import (
    ApprovedVersionImmutable,
    ReviewVersionNotFound,
)
from app.services.review_service import (
    DocumentTypeConfirmationMismatch,
    ReviewConflict,
    ReviewService,
    UnresolvedBlockingIssues,
)

router = APIRouter(prefix="/api/review", tags=["document review"])


class EditRequest(BaseModel):
    document: dict
    reason: str = "Reviewer correction"


class DecisionRequest(BaseModel):
    reason: str = ""


class ApprovalRequest(DecisionRequest):
    confirmed_document_type: DocumentType


class ReclassifyRequest(BaseModel):
    document_type: DocumentType
    reason: str = "Reviewer corrected document type"


@router.get("/tasks")
def list_review_tasks(
    service: ReviewService = Depends(get_review_service),
    user: AuthenticatedUser = Depends(require_reviewer),
) -> list[dict]:
    del user
    return service.list_queue()


@router.get("/approved-versions")
def list_approved_versions(
    service: ReviewService = Depends(get_review_service),
    user: AuthenticatedUser = Depends(require_reviewer),
) -> list[dict]:
    del user
    return [
        version.model_dump(mode="json")
        for version in service.list_versions(DocumentVersionStatus.APPROVED)
    ]


@router.post("/tasks/{task_id}/start")
def start_review(
    task_id: str,
    service: ReviewService = Depends(get_review_service),
    user: AuthenticatedUser = Depends(require_reviewer),
) -> dict:
    try:
        return service.start_review(task_id, user).model_dump(mode="json")
    except ReviewVersionNotFound as exc:
        raise HTTPException(status_code=404, detail="Review draft not found") from exc


@router.get("/versions/{version_id}")
def get_review_version(
    version_id: str,
    service: ReviewService = Depends(get_review_service),
    user: AuthenticatedUser = Depends(require_reviewer),
) -> dict:
    del user
    try:
        return service.get_detail(version_id)
    except ReviewVersionNotFound as exc:
        raise HTTPException(status_code=404, detail="Version not found") from exc


@router.post("/versions/{version_id}/validate")
def preview_validation(
    version_id: str,
    request: EditRequest,
    service: ReviewService = Depends(get_review_service),
    user: AuthenticatedUser = Depends(require_reviewer),
) -> dict:
    del user
    try:
        return service.preview_validation(version_id, request.document)
    except ReviewVersionNotFound as exc:
        raise HTTPException(status_code=404, detail="Version not found") from exc


@router.patch("/versions/{version_id}")
def save_edit(
    version_id: str,
    request: EditRequest,
    service: ReviewService = Depends(get_review_service),
    user: AuthenticatedUser = Depends(require_reviewer),
) -> dict:
    try:
        return service.save_edit(
            version_id,
            request.document,
            user,
            reason=request.reason,
        ).model_dump(mode="json")
    except ReviewConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/versions/{version_id}/reclassify")
def reclassify(
    version_id: str,
    request: ReclassifyRequest,
    service: ReviewService = Depends(get_review_service),
    user: AuthenticatedUser = Depends(require_reviewer),
) -> dict:
    try:
        return service.reclassify(
            version_id,
            request.document_type,
            user,
            reason=request.reason,
        ).model_dump(mode="json")
    except ReviewConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/versions/{version_id}/approve")
def approve(
    version_id: str,
    request: ApprovalRequest,
    service: ReviewService = Depends(get_review_service),
    user: AuthenticatedUser = Depends(require_reviewer),
) -> dict:
    try:
        return service.approve(
            version_id,
            user,
            reason=request.reason,
            confirmed_document_type=request.confirmed_document_type,
        ).model_dump(mode="json")
    except (
        DocumentTypeConfirmationMismatch,
        ReviewConflict,
        UnresolvedBlockingIssues,
        ApprovedVersionImmutable,
    ) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/versions/{version_id}/reject")
def reject(
    version_id: str,
    request: DecisionRequest,
    service: ReviewService = Depends(get_review_service),
    user: AuthenticatedUser = Depends(require_reviewer),
) -> dict:
    try:
        return service.reject(
            version_id,
            user,
            reason=request.reason,
        ).model_dump(mode="json")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
