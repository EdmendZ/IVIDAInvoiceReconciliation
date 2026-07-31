"""健康检查、开发诊断以及批准版本核对端点。"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.domain.reconciliation import ReconciliationRequest, ReconciliationResult
from app.services.reconciliation_service import reconcile
from app.api.auth_dependencies import require_reviewer
from app.api.dependencies import get_reconciliation_application_service
from app.domain.admin_users import AuthenticatedUser
from app.services.reconciliation_application_service import (
    DocumentNotApproved,
    ReconciliationApplicationService,
)

router = APIRouter(prefix="/api")
diagnostic_router = APIRouter(prefix="/api", tags=["development diagnostics"])


@router.get("/health")
def health() -> dict[str, str]:
    """只证明 API 进程可响应，不代表 Worker/外部模型均健康。"""

    settings = get_settings()
    return {
        "status": "ok",
        "service": settings.app_name,
        "environment": settings.app_env,
    }


@diagnostic_router.get("/reconciliations/example")
def reconciliation_example() -> dict:
    """开发环境使用的合成 JSON 示例，不读取业务数据库。"""

    return {
        "invoice": {
            "document_number": "INV-1001",
            "document_date": "2026-07-29",
            "purchase_order_number": "PO-7788",
            "currency": "AUD",
            "supplier": {"name": "Example Food Supplier"},
            "items": [
                {
                    "sku": "CHEESE-01",
                    "description": "Mozzarella Cheese 2kg",
                    "quantity": "10",
                    "unit": "case",
                    "unit_price": "25.00",
                    "line_total": "250.00",
                }
            ],
        },
        "receive_notes": [
            {
                "document_number": "RN-5001",
                "document_date": "2026-07-28",
                "purchase_order_number": "PO-7788",
                "currency": "AUD",
                "items": [
                    {
                        "sku": "CHEESE-01",
                        "description": "Mozzarella Cheese 2kg",
                        "quantity": "10",
                        "unit": "case",
                        "unit_price": "25.00",
                        "line_total": "250.00",
                    }
                ],
            }
        ],
    }


@diagnostic_router.post(
    "/reconciliations/compare",
    response_model=ReconciliationResult,
)
def compare_documents(request: ReconciliationRequest) -> ReconciliationResult:
    """开发诊断：跳过批准版本门禁直接调用纯核对函数。"""

    return reconcile(request)


class ApprovedReconciliationRequest(BaseModel):
    """真实核对只接收已批准 Version ID，而不是任意 Document JSON。"""

    invoice_version_id: str
    receive_note_version_ids: list[str] = Field(min_length=1)


@router.get("/reconciliations/candidates")
def list_reconciliation_candidates(
    invoice_version_id: str,
    service: ReconciliationApplicationService = Depends(
        get_reconciliation_application_service
    ),
    user: AuthenticatedUser = Depends(require_reviewer),
) -> list[dict]:
    """为已批准 Invoice 返回解释性 Receive Note 候选。"""

    del user
    try:
        return [
            candidate.model_dump(mode="json")
            for candidate in service.list_candidates(invoice_version_id)
        ]
    except DocumentNotApproved as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/reconciliations")
def create_reconciliation(
    request: ApprovedReconciliationRequest,
    service: ReconciliationApplicationService = Depends(
        get_reconciliation_application_service
    ),
    user: AuthenticatedUser = Depends(require_reviewer),
) -> dict:
    """验证批准版本、执行确定性核对并原子保存结果。"""

    try:
        record = service.compare(
            request.invoice_version_id,
            request.receive_note_version_ids,
            created_by=user.user_id,
        )
    except DocumentNotApproved as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return record.model_dump(mode="json")
