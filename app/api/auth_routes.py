from pydantic import BaseModel
from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status

from app.api.auth_dependencies import (
    get_auth_service,
    require_reviewer,
)
from app.core.config import get_settings
from app.domain.admin_users import AuthenticatedUser
from app.services.auth_service import AuthService, InvalidCredentials

router = APIRouter(prefix="/api/auth", tags=["review authentication"])


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/login", response_model=AuthenticatedUser)
def login(
    request: LoginRequest,
    response: Response,
    service: AuthService = Depends(get_auth_service),
) -> AuthenticatedUser:
    try:
        token, user = service.login(request.username, request.password)
    except InvalidCredentials as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc
    response.set_cookie(
        "ivida_review_session",
        token,
        httponly=True,
        secure=get_settings().app_env.lower() == "prod",
        samesite="lax",
        max_age=8 * 60 * 60,
        path="/",
    )
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    ivida_review_session: str | None = Cookie(default=None),
    service: AuthService = Depends(get_auth_service),
) -> None:
    service.logout(ivida_review_session or "")
    response.delete_cookie("ivida_review_session", path="/")


@router.get("/me", response_model=AuthenticatedUser)
def me(user: AuthenticatedUser = Depends(require_reviewer)) -> AuthenticatedUser:
    return user
