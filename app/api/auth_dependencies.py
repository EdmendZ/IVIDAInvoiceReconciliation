"""FastAPI 认证依赖：从 HttpOnly Cookie 恢复用户并执行角色门禁。"""

from functools import lru_cache

from fastapi import Cookie, Depends, HTTPException, status

from app.domain.admin_users import AdminRole, AuthenticatedUser
from app.infra.database import get_session_factory
from app.infra.postgres_admin_repository import PostgresAdminRepository
from app.services.auth_service import AuthService


@lru_cache
def get_auth_service() -> AuthService:
    """构造可缓存的认证服务，复用同一 Repository 配置。"""

    return AuthService(PostgresAdminRepository(get_session_factory()))


def authenticate_session(
    ivida_review_session: str | None = Cookie(default=None),
    service: AuthService = Depends(get_auth_service),
) -> AuthenticatedUser:
    """校验 Session Cookie；缺失、过期或无效统一返回 401。"""

    user = service.authenticate(ivida_review_session or "")
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    return user


def require_reviewer(
    user: AuthenticatedUser = Depends(authenticate_session),
) -> AuthenticatedUser:
    """允许 reviewer/admin 访问单据业务接口。"""

    return user


def require_admin(
    user: AuthenticatedUser = Depends(require_reviewer),
) -> AuthenticatedUser:
    """只允许 admin 执行账号管理等高权限操作。"""

    if user.role != AdminRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required",
        )
    return user
