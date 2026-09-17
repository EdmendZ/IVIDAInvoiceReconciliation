from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.infra.database import Base
from app.infra.database_models import AdminSessionRow, AdminUserRow
from app.infra.postgres_admin_repository import PostgresAdminRepository
from app.services.auth_service import AuthService, InvalidCredentials
from run_local_demo import build_start_command
from setup_dev_admin import ensure_development_environment, setup_dev_admin


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, class_=Session, expire_on_commit=False)


def test_dev_admin_setup_creates_then_resets_and_revokes_sessions(
    session_factory: sessionmaker[Session],
) -> None:
    first_password = "first-password-123"
    second_password = "second-password-456"
    assert setup_dev_admin(
        session_factory,
        username="adminuser",
        password=first_password,
        now=datetime(2026, 9, 17, tzinfo=UTC),
    ) == "created"

    auth = AuthService(PostgresAdminRepository(session_factory))
    token, user = auth.login("adminuser", first_password)
    assert token
    assert user.role.value == "admin"

    assert setup_dev_admin(
        session_factory,
        username="adminuser",
        password=second_password,
        now=datetime(2026, 9, 17, tzinfo=UTC),
    ) == "reset"

    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(AdminUserRow)) == 1
        assert session.scalar(select(func.count()).select_from(AdminSessionRow)) == 0
    with pytest.raises(InvalidCredentials):
        auth.login("adminuser", first_password)
    assert auth.login("adminuser", second_password)[1].username == "adminuser"


def test_dev_admin_setup_refuses_production() -> None:
    with pytest.raises(SystemExit, match="disabled in production"):
        ensure_development_environment("production")
    ensure_development_environment("dev")


def test_python_launcher_delegates_to_existing_powershell_entrypoint() -> None:
    root = Path("C:/example/IVIDAInvoiceReconciliation")
    command = build_start_command(root)
    assert command == [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(root / "start_local_demo.ps1"),
    ]
