"""登录、登出和当前用户查询的 HTTP 适配层。"""

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
    """登录请求；密码只在当前请求内交给 AuthService 验证。"""

    username: str
    password: str


@router.post("/login", response_model=AuthenticatedUser)
def login(
    request: LoginRequest,
    response: Response,
    service: AuthService = Depends(get_auth_service),
) -> AuthenticatedUser:
    """创建数据库 Session，并把原 Token 放入 HttpOnly Cookie。"""

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
    """删除数据库 Session 与浏览器 Cookie；重复登出保持安全。"""

    service.logout(ivida_review_session or "")
    response.delete_cookie("ivida_review_session", path="/")


@router.get("/me", response_model=AuthenticatedUser)
def me(user: AuthenticatedUser = Depends(require_reviewer)) -> AuthenticatedUser:
    """返回前端建立登录态所需的最小用户信息。"""

    return user
