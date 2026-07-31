"""人工审核、版本编辑、重分类、批准和驳回端点。"""

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
    """保存或预校验人工修订后的完整 Document JSON。"""

    document: dict
    reason: str = "Reviewer correction"


class DecisionRequest(BaseModel):
    """批准/驳回原因；驳回时 Service 强制非空。"""

    reason: str = ""


class ApprovalRequest(DecisionRequest):
    """批准时再次提交人工确认的单据类型。"""

    confirmed_document_type: DocumentType


class ReclassifyRequest(BaseModel):
    """把最新 Draft Version 修正为另一种业务类型。"""

    document_type: DocumentType
    reason: str = "Reviewer corrected document type"


@router.get("/tasks")
def list_review_tasks(
    service: ReviewService = Depends(get_review_service),
    user: AuthenticatedUser = Depends(require_reviewer),
) -> list[dict]:
    """返回每个 Task 的最新审核状态和规则问题数量。"""

    del user
    return service.list_queue()


@router.get("/approved-versions")
def list_approved_versions(
    service: ReviewService = Depends(get_review_service),
    user: AuthenticatedUser = Depends(require_reviewer),
) -> list[dict]:
    """返回可进入候选匹配与核对的不可变版本。"""

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
    """幂等地从机器 Draft 创建或返回首个人工 Version。"""

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
    """返回版本、证据、问题、动作和安全模型溯源。"""

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
    """无持久化地验证编辑内容，供前端 Live Validation 使用。"""

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
    """将人工修改保存为下一 Version，不覆盖当前版本。"""

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
    """修正 Invoice/Receive Note 类型并创建审计版本。"""

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
    """在 Service 重新校验后执行 draft -> approved。"""

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
    """将 Draft Version 驳回并要求记录原因。"""

    try:
        return service.reject(
            version_id,
            user,
            reason=request.reason,
        ).model_dump(mode="json")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
