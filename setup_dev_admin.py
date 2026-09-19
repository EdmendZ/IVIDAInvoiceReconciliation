"""Create or reset the local development administrator from an IDE or terminal."""

from __future__ import annotations

import os
import secrets
from datetime import UTC, datetime
from uuid import uuid4

from argon2 import PasswordHasher
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.infra.database import get_session_factory
from app.infra.database_models import AdminSessionRow, AdminUserRow


DEFAULT_DEV_ADMIN_USERNAME = "adminuser"


def ensure_development_environment(app_env: str) -> None:
    """Refuse the convenience bootstrap in production-like environments."""

    if app_env.strip().casefold() in {"prod", "production"}:
        raise SystemExit("Development administrator setup is disabled in production.")


def setup_dev_admin(
    session_factory: sessionmaker[Session],
    *,
    username: str,
    password: str,
    now: datetime | None = None,
) -> str:
    """Create or reset one Admin and revoke every existing browser session."""

    username = username.strip()
    if not username:
        raise ValueError("Username is required")
    if len(password) < 12:
        raise ValueError("Password must contain at least 12 characters")

    created_at = now or datetime.now(UTC)
    password_hash = PasswordHasher().hash(password)
    with session_factory.begin() as session:
        user = session.scalar(
            select(AdminUserRow).where(AdminUserRow.username == username)
        )
        if user is None:
            user = AdminUserRow(
                user_id=str(uuid4()),
                username=username,
                password_hash=password_hash,
                role="admin",
                is_active=True,
                created_at=created_at,
            )
            session.add(user)
            outcome = "created"
        else:
            user.password_hash = password_hash
            user.role = "admin"
            user.is_active = True
            outcome = "reset"
        session.execute(
            delete(AdminSessionRow).where(AdminSessionRow.user_id == user.user_id)
        )
    return outcome


def main() -> None:
    settings = get_settings()
    ensure_development_environment(settings.app_env)
    username = os.environ.get(
        "IVIDA_DEV_ADMIN_USERNAME",
        DEFAULT_DEV_ADMIN_USERNAME,
    )
    password = secrets.token_urlsafe(18)
    outcome = setup_dev_admin(
        get_session_factory(),
        username=username,
        password=password,
    )
    print(f"Development admin {outcome}.")
    print(f"Username: {username.strip()}")
    print(f"Temporary password: {password}")
    print("Running this file again rotates the password and signs out old sessions.")


if __name__ == "__main__":
    main()
