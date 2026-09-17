from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import setup_demo_data as demo
from app.domain.admin_users import AdminRole, AuthenticatedUser
from app.domain.workspace import WorkspaceScopeKey
from app.infra.database import Base
from app.infra.database_models import (
    AdminUserRow,
    DocumentDraftRow,
    ExtractionRunRow,
    ExtractionTaskRow,
    WorkspaceDocumentRow,
    WorkspacePreviewRow,
    WorkspaceRevisionRow,
)
from app.infra.postgres_task_repository import PostgresExtractionTaskRepository
from app.infra.postgres_workspace_repository import PostgresWorkspaceRepository
from app.services.document_upload_service import DocumentUploadService
from app.services.workspace_service import WorkspaceService
from app.workers.workspace_worker import WorkspaceWorker


class MemoryStorage:
    bucket_name = "demo-fixtures"

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
def runtime() -> tuple[demo.DemoRuntime, MemoryStorage]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    class UTCSession(Session):
        pass

    @event.listens_for(UTCSession, "loaded_as_persistent")
    def restore_sqlite_timezone(_session, instance) -> None:
        # SQLite drops timezone offsets. Production PostgreSQL preserves them;
        # restore UTC in this portable entrypoint test before DTO validation.
        for attribute in instance.__mapper__.column_attrs:
            value = getattr(instance, attribute.key)
            if isinstance(value, datetime) and value.tzinfo is None:
                setattr(instance, attribute.key, value.replace(tzinfo=UTC))

    factory = sessionmaker(bind=engine, class_=UTCSession, expire_on_commit=False)
    actor = AuthenticatedUser(
        user_id="00000000-0000-0000-0000-000000000013",
        username="adminuser",
        role=AdminRole.ADMIN,
    )
    with factory.begin() as session:
        session.add(
            AdminUserRow(
                user_id=actor.user_id,
                username=actor.username,
                password_hash="test-only-not-a-login-secret",
                role="admin",
                is_active=True,
                created_at=datetime(2026, 9, 17, tzinfo=UTC),
            )
        )
    storage = MemoryStorage()
    repository = PostgresWorkspaceRepository(factory)
    scope = WorkspaceScopeKey(tenant_id="demo-tenant", store_id="demo-store")
    service = WorkspaceService(
        repository,
        DocumentUploadService(
            storage=storage,
            repository=PostgresExtractionTaskRepository(factory),
            max_bytes=1024 * 1024,
        ),
        storage,
        scope,
    )
    yield (
        demo.DemoRuntime(
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
    models = (
        ExtractionTaskRow,
        ExtractionRunRow,
        DocumentDraftRow,
        WorkspaceDocumentRow,
        WorkspaceRevisionRow,
        WorkspacePreviewRow,
    )
    with factory() as session:
        return tuple(
            session.scalar(select(func.count()).select_from(model)) or 0
            for model in models
        )


def test_d04_production_refuses_before_building_external_resources(monkeypatch) -> None:
    monkeypatch.setattr(
        demo,
        "get_settings",
        lambda: SimpleNamespace(app_env="production"),
    )

    def forbidden(_settings):
        raise AssertionError("database or object storage was accessed")

    monkeypatch.setattr(demo, "_build_runtime", forbidden)
    with pytest.raises(SystemExit, match="disabled in production"):
        demo.main()


def test_d05_six_deterministic_english_pdfs_and_four_visible_states(runtime) -> None:
    configured, storage = runtime
    results = demo.setup_demo_data(configured)

    assert len(storage.objects) == 6
    assert len({value for value in storage.objects.values()}) == 6
    for value in storage.objects.values():
        assert value.startswith(b"%PDF-1.4")
        assert value.rstrip().endswith(b"%%EOF")
        assert b"IVIDA DEVELOPMENT DEMO FIXTURE" in value
        assert b"Currency: AUD" in value
        assert b"bypasses OCR and model extraction" in value

    observed = {
        result.scenario: (result.display_status, result.preview_outcome)
        for result in results
    }
    assert observed == {
        "invoice_waiting_for_receive_note": ("waiting_counterpart", None),
        "receive_note_waiting_for_invoice": ("waiting_counterpart", None),
        "automatic_consistent": ("awaiting_confirmation", "consistent"),
        "automatic_quantity_difference": ("needs_attention", "difference"),
    }
    assert all(result.document_ids for result in results)


def test_d06_repeat_reuses_task_run_draft_document_revision_and_preview(runtime) -> None:
    configured, _storage = runtime
    first = demo.setup_demo_data(configured)
    first_counts = _counts(configured.session_factory)
    second = demo.setup_demo_data(configured)
    second_counts = _counts(configured.session_factory)

    assert first_counts == second_counts == (6, 6, 6, 6, 6, 2)
    assert first == second
    with configured.session_factory() as session:
        runs = list(session.scalars(select(ExtractionRunRow)))
        assert all(
            run.raw_output["fixture_kind"] == demo.DEMO_FIXTURE_MARKER
            for run in runs
        )


def test_d07_output_contains_only_scenario_ids_and_states(runtime) -> None:
    configured, _storage = runtime
    rendered = demo.format_results(demo.setup_demo_data(configured))
    records = [json.loads(line) for line in rendered.splitlines()]
    assert len(records) == 4
    assert all(
        set(record)
        == {"scenario", "document_ids", "display_status", "preview_outcome"}
        for record in records
    )
    lowered = rendered.casefold()
    for forbidden in ("password", "token", "dsn", "postgresql", "minio_secret"):
        assert forbidden not in lowered
