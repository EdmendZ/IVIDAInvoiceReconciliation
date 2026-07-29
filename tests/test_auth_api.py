from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.api.auth_dependencies import get_auth_service
from app.domain.admin_users import AdminRole
from app.infra.database import Base
from app.infra.postgres_admin_repository import PostgresAdminRepository
from app.main import app
from app.services.auth_service import AuthService


def test_reviewer_can_login_and_session_is_http_only() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    service = AuthService(PostgresAdminRepository(factory))
    service.create_user(
        username="reviewer",
        password="correct-password-123",
        role=AdminRole.REVIEWER,
    )
    app.dependency_overrides[get_auth_service] = lambda: service
    client = TestClient(app)
    try:
        response = client.post(
            "/api/auth/login",
            json={
                "username": "reviewer",
                "password": "correct-password-123",
            },
        )
        assert response.status_code == 200
        assert response.json()["role"] == "reviewer"
        assert response.cookies.get("ivida_review_session")
        assert "HttpOnly" in response.headers["set-cookie"]

        me = client.get("/api/auth/me")
        assert me.status_code == 200
        assert me.json()["username"] == "reviewer"

        logout = client.post("/api/auth/logout")
        assert logout.status_code == 204
        assert client.get("/api/auth/me").status_code == 401
    finally:
        app.dependency_overrides.clear()
