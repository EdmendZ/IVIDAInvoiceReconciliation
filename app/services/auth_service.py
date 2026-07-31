"""后台审核账号与短期 Session 的认证服务。"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import uuid4

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app.domain.admin_users import (
    AdminRole,
    AdminSession,
    AdminUser,
    AuthenticatedUser,
)


class InvalidCredentials(ValueError):
    pass


class AdminRepository(Protocol):
    def create_user(self, user: AdminUser) -> None: ...
    def get_user_by_username(self, username: str) -> AdminUser | None: ...
    def create_session(self, admin_session: AdminSession) -> None: ...
    def get_session_user(
        self, token_hash: str, now: datetime
    ) -> AuthenticatedUser | None: ...
    def delete_session(self, token_hash: str) -> None: ...


class AuthService:
    """使用 Argon2 保存密码 Hash，并且只在数据库保存 Session Token Hash。"""

    def __init__(
        self,
        repository: AdminRepository,
        *,
        password_hasher: PasswordHasher | None = None,
        session_hours: int = 8,
    ) -> None:
        self._repository = repository
        self._hasher = password_hasher or PasswordHasher()
        self._session_hours = session_hours

    def create_user(
        self,
        *,
        username: str,
        password: str,
        role: AdminRole,
    ) -> AdminUser:
        username = username.strip()
        if not username:
            raise ValueError("Username is required")
        if len(password) < 12:
            raise ValueError("Password must contain at least 12 characters")
        now = datetime.now(UTC)
        user = AdminUser(
            user_id=str(uuid4()),
            username=username,
            password_hash=self._hasher.hash(password),
            role=role,
            is_active=True,
            created_at=now,
        )
        self._repository.create_user(user)
        return user

    def login(self, username: str, password: str) -> tuple[str, AuthenticatedUser]:
        user = self._repository.get_user_by_username(username.strip())
        if user is None or not user.is_active:
            raise InvalidCredentials("Invalid username or password")
        try:
            self._hasher.verify(user.password_hash, password)
        except VerifyMismatchError as exc:
            raise InvalidCredentials("Invalid username or password") from exc
        # 浏览器持有原 Token；数据库只保存 Hash，数据库泄露时不能直接复用会话。
        token = secrets.token_urlsafe(48)
        now = datetime.now(UTC)
        self._repository.create_session(
            AdminSession(
                session_token_hash=self.hash_token(token),
                user_id=user.user_id,
                expires_at=now + timedelta(hours=self._session_hours),
                created_at=now,
            )
        )
        return token, AuthenticatedUser(
            user_id=user.user_id,
            username=user.username,
            role=user.role,
        )

    def authenticate(self, token: str) -> AuthenticatedUser | None:
        if not token:
            return None
        return self._repository.get_session_user(
            self.hash_token(token),
            datetime.now(UTC),
        )

    def logout(self, token: str) -> None:
        if token:
            self._repository.delete_session(self.hash_token(token))

    @staticmethod
    def hash_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()
