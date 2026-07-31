"""向已认证 UI 暴露最小 Worker 运行状态。"""

from fastapi import APIRouter, Depends

from app.api.auth_dependencies import require_reviewer
from app.api.dependencies import get_runtime_status_service
from app.domain.admin_users import AuthenticatedUser
from app.domain.worker_runtime import RuntimeStatus
from app.services.runtime_status_service import RuntimeStatusService

router = APIRouter(prefix="/api/runtime", tags=["runtime"])


@router.get("/status", response_model=RuntimeStatus)
def runtime_status(
    user: AuthenticatedUser = Depends(require_reviewer),
    service: RuntimeStatusService = Depends(get_runtime_status_service),
) -> RuntimeStatus:
    """根据最近心跳返回 online/offline，不泄露内部连接信息。"""

    del user
    return service.status()
