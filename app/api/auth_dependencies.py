from functools import lru_cache

from fastapi import Cookie, Depends, HTTPException, status

from app.domain.admin_users import AdminRole, AuthenticatedUser
from app.infra.database import get_session_factory
from app.infra.postgres_admin_repository import PostgresAdminRepository
from app.services.auth_service import AuthService


@lru_cache
def get_auth_service() -> AuthService:
    return AuthService(PostgresAdminRepository(get_session_factory()))


def authenticate_session(
    ivida_review_session: str | None = Cookie(default=None),
    service: AuthService = Depends(get_auth_service),
) -> AuthenticatedUser:
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
    return user


def require_admin(
    user: AuthenticatedUser = Depends(require_reviewer),
) -> AuthenticatedUser:
    if user.role != AdminRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required",
        )
    return user
