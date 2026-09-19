from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import setup_evaluation_data as evaluation
from app.domain.admin_users import AdminRole, AuthenticatedUser
from app.domain.workspace import WorkspaceScopeKey
from app.infra import database_models as models
from app.infra.database import Base
from app.infra.postgres_task_repository import PostgresExtractionTaskRepository
from app.infra.postgres_workspace_repository import PostgresWorkspaceRepository
from app.services.document_upload_service import DocumentUploadService
from app.services.workspace_service import WorkspaceService
from app.workers.workspace_worker import WorkspaceWorker
from setup_demo_data import DemoRuntime


class MemoryStorage:
    bucket_name = "evaluation-fixtures"

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, object_key: str, data: bytes, content_type: str) -> None:
        assert content_type == "application/pdf"
        self.objects[object_key] = data

    def delete(self, object_key: str) -> None:
        self.objects.pop(object_key, None)

    def get(self, object_key: str) -> bytes:
        return self.objects[object_key]


@pytest.fixture
def runtime() -> tuple[DemoRuntime, MemoryStorage]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    class UTCSession(Session):
        pass

    @event.listens_for(UTCSession, "loaded_as_persistent")
    def restore_sqlite_timezone(_session, instance) -> None:
        for attribute in instance.__mapper__.column_attrs:
            value = getattr(instance, attribute.key)
            if isinstance(value, datetime) and value.tzinfo is None:
                setattr(instance, attribute.key, value.replace(tzinfo=UTC))

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=UTCSession, expire_on_commit=False)
    actor = AuthenticatedUser(
        user_id="00000000-0000-0000-0000-000000000013",
        username="adminuser",
        role=AdminRole.ADMIN,
    )
    with factory.begin() as session:
        session.add(
            models.AdminUserRow(
                user_id=actor.user_id,
                username=actor.username,
                password_hash="test-only-not-a-login-secret",
                role="admin",
                is_active=True,
                created_at=datetime(2026, 9, 17, tzinfo=UTC),
            )
        )
    storage = MemoryStorage()
    scope = WorkspaceScopeKey(tenant_id="evaluation-tenant", store_id="evaluation-store")
    repository = PostgresWorkspaceRepository(factory)
    service = WorkspaceService(
        repository,
        DocumentUploadService(
            storage=storage,
            repository=PostgresExtractionTaskRepository(factory),
            max_bytes=4 * 1024 * 1024,
        ),
        storage,
        scope,
    )
    yield (
        DemoRuntime(
            session_factory=factory,
            service=service,
            repository=repository,
            worker=WorkspaceWorker(repository, scope),
            actor=actor,
        ),
        storage,
    )
    engine.dispose()


def _counts(factory: sessionmaker[Session]) -> tuple[int, ...]:
    tables = (
        models.ExtractionTaskRow,
        models.ExtractionRunRow,
        models.DocumentDraftRow,
        models.WorkspaceDocumentRow,
        models.WorkspaceRevisionRow,
        models.WorkspacePreviewRow,
        models.WorkspaceActionRow,
        models.WorkspaceRequestRow,
    )
    with factory() as session:
        return tuple(
            session.scalar(select(func.count()).select_from(table)) or 0
            for table in tables
        )


def test_production_refuses_before_building_runtime(monkeypatch) -> None:
    monkeypatch.setattr(
        evaluation,
        "get_settings",
        lambda: SimpleNamespace(app_env="production"),
    )
    monkeypatch.setattr(
        evaluation,
        "_build_runtime",
        lambda _settings: pytest.fail("runtime must not be built in production"),
    )
    with pytest.raises(SystemExit, match="disabled in production"):
        evaluation.main()


def test_imports_all_cases_and_repeat_is_idempotent(runtime) -> None:
    if not evaluation.MANIFEST_PATH.is_file():
        pytest.skip("local evaluation_data is not present")
    configured, storage = runtime

    first = evaluation.setup_evaluation_data(configured)
    first_counts = _counts(configured.session_factory)
    second = evaluation.setup_evaluation_data(configured)
    second_counts = _counts(configured.session_factory)

    assert len(first) == 8
    assert first == second
    assert len(storage.objects) == 17
    assert first_counts == second_counts == (17, 17, 17, 17, 17, 7, 34, 17)
    observed = {
        item.case_id: (item.display_status, item.match_status, item.preview_outcome)
        for item in first
    }
    assert observed["case-01-exact-single"] == (
        "awaiting_confirmation",
        "selected",
        "consistent",
    )
    assert observed["case-02-exact-split-delivery"] == (
        "awaiting_confirmation",
        "selected",
        "consistent",
    )
    assert observed["case-03-short-delivery"] == (
        "needs_attention",
        "selected",
        "difference",
    )
    assert observed["case-08-po-mismatch"] == (
        "needs_attention",
        "needs_selection",
        None,
    )


def test_output_contains_only_case_ids_and_visible_states(runtime) -> None:
    if not evaluation.MANIFEST_PATH.is_file():
        pytest.skip("local evaluation_data is not present")
    configured, _storage = runtime
    rendered = evaluation.format_results(evaluation.setup_evaluation_data(configured))
    records = [json.loads(line) for line in rendered.splitlines()]
    assert len(records) == 8
    assert all(
        set(record)
        == {
            "case_id",
            "invoice_document_id",
            "receive_note_document_ids",
            "display_status",
            "match_status",
            "preview_outcome",
        }
        for record in records
    )
    lowered = rendered.casefold()
    for forbidden in ("password", "token", "dsn", "postgresql", "minio_secret"):
        assert forbidden not in lowered
