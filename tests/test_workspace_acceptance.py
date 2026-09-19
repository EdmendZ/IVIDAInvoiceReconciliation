"""End-to-end workspace acceptance over a disposable PostgreSQL schema.

The API and worker use the production service and repository objects.  The
fixture normalizer is deliberately small: it represents the already trusted
output of an external parser/normalizer without contacting a model service.
"""

from __future__ import annotations

import importlib.util
import ast
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

import app.api.dependencies as dependency_module
import app.api.workspace_routes as workspace_routes
from app.api.auth_dependencies import require_reviewer
from app.domain.admin_users import AdminRole, AuthenticatedUser
from app.domain.documents import DocumentType, Invoice
from app.domain.normalization import NormalizationResult
from app.domain.parsing import ParseResult, ParseState, ParserPollResult, ParserSubmission
from app.domain.workspace import WorkspaceScopeKey
from app.infra import database_models as models
from app.infra.database import Base
from app.infra.postgres_draft_repository import PostgresDocumentDraftRepository
from app.infra.postgres_extraction_run_repository import PostgresExtractionRunRepository
from app.infra.postgres_parse_repository import PostgresParseResultRepository
from app.infra.postgres_task_repository import PostgresExtractionTaskRepository
from app.infra.postgres_workspace_repository import PostgresWorkspaceRepository
from app.main import app
from app.services.document_upload_service import DocumentUploadService
from app.services.validation_service import ValidationService
from app.services.workspace_service import WorkspaceService
from app.workers.extraction_worker import ExtractionWorker
from app.workers.workspace_worker import WorkspaceWorker


ROOT = Path(__file__).resolve().parents[1]
REVIEWER = AuthenticatedUser(
    user_id="00000000-0000-0000-0000-000000000099",
    username="workspace-acceptance",
    role=AdminRole.REVIEWER,
)


def uid() -> str:
    return str(uuid4())


def now() -> datetime:
    return datetime.now(UTC)


class FixtureStorage:
    """In-memory object storage with the real upload service contract."""

    bucket_name = "workspace-acceptance"

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, object_key: str, data: bytes, content_type: str) -> None:
        del content_type
        self.objects[object_key] = data

    def delete(self, object_key: str) -> None:
        self.objects.pop(object_key, None)

    def get(self, object_key: str) -> bytes:
        return self.objects[object_key]


class FixtureNormalizer:
    """Persist deterministic normalized output as an extraction draft."""

    def __init__(self, factory: sessionmaker) -> None:
        self.factory = factory

    def ready(self, intake: dict, payload: dict) -> None:
        with self.factory.begin() as session:
            run = session.get(models.ExtractionRunRow, intake["run_id"])
            assert run is not None
            run.status = "ready_for_review"
            run.phase_error_code = None
            session.add(
                models.DocumentDraftRow(
                    draft_id=uid(),
                    run_id=run.run_id,
                    task_id=intake["task_id"],
                    document_type=payload["document_type"],
                    normalized_json=payload,
                    validation_state="valid",
                    created_at=now(),
                    updated_at=now(),
                )
            )


class FixtureParser:
    """Deterministic parser stand-in; it persists a real parse result via the worker."""

    provider_name = "fixture-parser"
    model_name = "fixture-parser-1"

    def submit(self, *, filename: str, content_type: str, content: bytes) -> ParserSubmission:
        del content_type, content
        return ParserSubmission(remote_job_id=filename)

    def poll(self, remote_job_id: str) -> ParserPollResult:
        return ParserPollResult(
            state=ParseState.SUCCEEDED,
            result=ParseResult(
                provider=self.provider_name,
                model_name=self.model_name,
                markdown=remote_job_id,
                page_count=1,
                artifact_archive=b"fixture-parse-artifact",
            ),
        )


class FixtureModelNormalizer:
    """Deterministic normalizer stand-in returning a validated Invoice/Receive Note."""

    provider_name = "fixture-normalizer"
    model_name = "fixture-normalizer-1"
    prompt_version = "fixture-prompt-1"

    def __init__(self, documents: dict[str, dict]) -> None:
        self.documents = documents

    def normalize(self, *, document_type: DocumentType, parse_result: ParseResult) -> NormalizationResult:
        document = self.documents[parse_result.markdown]
        if document_type is DocumentType.INVOICE:
            normalized = Invoice.model_validate(document)
        else:
            from app.domain.documents import ReceiveNote

            normalized = ReceiveNote.model_validate(document)
        return NormalizationResult(document=normalized, raw_response={"fixture": True})


@pytest.fixture(scope="module")
def database():
    value = os.environ.get("WORKSPACE_TEST_DATABASE_URL")
    if not value:
        pytest.skip("WORKSPACE_TEST_DATABASE_URL must point to a disposable PostgreSQL database")
    url = make_url(value)
    if url.get_backend_name() != "postgresql" or not (url.database or "").endswith("_workspace_test"):
        pytest.fail("Refusing non-disposable workspace test database")
    schema = "ws_accept_" + uuid4().hex
    assert re.fullmatch(r"ws_accept_[a-f0-9]{32}", schema)
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    try:
        Base.metadata.create_all(
            engine,
            tables=[table for table in Base.metadata.sorted_tables if not table.name.startswith("ws_")],
        )
        migration_spec = importlib.util.spec_from_file_location(
            "workspace_acceptance_migration",
            ROOT / "migrations/versions/20260916_15_workspace.py",
        )
        assert migration_spec and migration_spec.loader
        migration = importlib.util.module_from_spec(migration_spec)
        migration_spec.loader.exec_module(migration)
        with engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


@pytest.fixture()
def harness(database, monkeypatch):
    factory = sessionmaker(database, autoflush=False, expire_on_commit=False)
    with factory.begin() as session:
        session.merge(
            models.AdminUserRow(
                user_id=REVIEWER.user_id,
                username=REVIEWER.username,
                password_hash="fixture-only",
                role="reviewer",
                is_active=True,
                created_at=now(),
            )
        )
    scope = WorkspaceScopeKey(tenant_id=uid(), store_id="acceptance-store")
    storage = FixtureStorage()
    upload_service = DocumentUploadService(
        storage=storage,
        repository=PostgresExtractionTaskRepository(factory),
        max_bytes=1024 * 1024,
    )
    repository = PostgresWorkspaceRepository(factory)
    service = WorkspaceService(repository, upload_service, storage, scope)
    worker = WorkspaceWorker(repository, scope)
    settings = type(
        "WorkspaceAcceptanceSettings",
        (),
        {"workspace_enabled": True, "upload_max_bytes": 1024 * 1024},
    )()
    monkeypatch.setattr(dependency_module, "get_settings", lambda: settings)
    monkeypatch.setattr(workspace_routes, "get_settings", lambda: settings)
    old_reviewer = app.dependency_overrides.get(require_reviewer)
    old_service = app.dependency_overrides.get(dependency_module.get_workspace_service)
    old_runtime = app.dependency_overrides.get(dependency_module.get_workspace_runtime_service)
    app.dependency_overrides[require_reviewer] = lambda: REVIEWER
    app.dependency_overrides[dependency_module.get_workspace_service] = lambda: service
    app.dependency_overrides[dependency_module.get_workspace_runtime_service] = lambda: service
    try:
        with TestClient(app) as client:
            yield client, repository, worker, FixtureNormalizer(factory), scope, storage, factory
    finally:
        if old_reviewer is None:
            app.dependency_overrides.pop(require_reviewer, None)
        else:
            app.dependency_overrides[require_reviewer] = old_reviewer
        if old_service is None:
            app.dependency_overrides.pop(dependency_module.get_workspace_service, None)
        else:
            app.dependency_overrides[dependency_module.get_workspace_service] = old_service
        if old_runtime is None:
            app.dependency_overrides.pop(dependency_module.get_workspace_runtime_service, None)
        else:
            app.dependency_overrides[dependency_module.get_workspace_runtime_service] = old_runtime


def payload(kind: str, number: str, *, quantity: str = "10", supplier: str = "Fresh Foods") -> dict:
    return {
        "document_type": kind,
        "document_number": number,
        "currency": "AUD",
        "document_date": "2026-09-16",
        "purchase_order_number": "PO-1",
        "supplier": {"name": supplier},
        "items": [
            {
                "sku": "EGGS",
                "description": "Free Range Eggs",
                "quantity": quantity,
                "unit": "bag",
                "unit_price": "10.00",
                "line_total": str(int(quantity) * 10) + ".00",
            }
        ],
    }


def upload(client: TestClient, kind: str, filename: str) -> dict:
    response = client.post(
        "/api/workspace/documents",
        data={"document_type": kind},
        files={"file": (filename, b"%PDF-1.7 fixture " + filename.encode(), "application/pdf")},
        headers={"Idempotency-Key": uid()},
    )
    assert response.status_code == 201, response.text
    return response.json()


def make_ready(normalizer: FixtureNormalizer, intake: dict, kind: str, number: str, **kwargs) -> None:
    normalizer.ready(intake, payload(kind, number, **kwargs))


def drive(harness, invoice: dict, receivings: list[dict]) -> dict:
    client, repository, worker, normalizer, scope, _storage, _factory = harness
    for receiving in receivings:
        make_ready(normalizer, receiving, "receive_note", receiving["number"], quantity=receiving.get("quantity", "10"))
    make_ready(normalizer, invoice, "invoice", invoice["number"], quantity=invoice.get("quantity", "10"))
    summary = worker.tick()
    assert summary.errors == 0
    return client.get(f"/api/workspace/documents/{invoice['document']['document_id']}").json()


def test_invoice_first_and_worker_preview(harness):
    client, _repository, worker, normalizer, _scope, _storage, _factory = harness
    invoice = upload(client, "invoice", "invoice-first.pdf")
    make_ready(normalizer, invoice, "invoice", "INV-FIRST")
    assert worker.tick().previews_saved == 1
    waiting = client.get(f"/api/workspace/documents/{invoice['document']['document_id']}").json()
    assert waiting["document"]["display_status"] == "waiting_counterpart"

    receiving = upload(client, "receive_note", "rn-later.pdf")
    make_ready(normalizer, receiving, "receive_note", "RN-LATER")
    tick = worker.tick()
    assert tick.previews_saved == 1
    detail = client.get(f"/api/workspace/documents/{invoice['document']['document_id']}").json()
    assert detail["preview"]["result"]["outcome"] == "consistent"
    assert detail["preview"]["result"]["coverage"] == "full"
    assert detail["document"]["display_status"] == "awaiting_confirmation"


def test_real_extraction_worker_then_workspace_worker(harness):
    client, repository, workspace_worker, _normalizer, scope, storage, factory = harness
    invoice = upload(client, "invoice", "pipeline-invoice.pdf")
    receiving = upload(client, "receive_note", "pipeline-rn.pdf")
    documents = {
        "pipeline-invoice.pdf": payload("invoice", "INV-PIPELINE"),
        "pipeline-rn.pdf": payload("receive_note", "RN-PIPELINE"),
    }
    extraction_worker = ExtractionWorker(
        parser=FixtureParser(),
        storage=storage,
        task_repository=PostgresExtractionTaskRepository(factory),
        run_repository=PostgresExtractionRunRepository(factory),
        parse_repository=PostgresParseResultRepository(factory),
        normalizer=FixtureModelNormalizer(documents),
        draft_repository=PostgresDocumentDraftRepository(factory),
        validation_service=ValidationService(),
        poll_interval_seconds=0,
    )
    for _ in range(12):
        if not extraction_worker.run_once("workspace-acceptance-extractor"):
            break
    invoice_run = PostgresExtractionRunRepository(factory).get(invoice["run_id"])
    receiving_run = PostgresExtractionRunRepository(factory).get(receiving["run_id"])
    assert invoice_run and invoice_run.status.value in {"ready_for_review", "succeeded"}, (
        invoice_run.status if invoice_run else None,
        invoice_run.error_message if invoice_run else None,
        invoice_run.phase_error_code if invoice_run else None,
    )
    assert receiving_run and receiving_run.status.value in {"ready_for_review", "succeeded"}, (
        receiving_run.status if receiving_run else None,
        receiving_run.error_message if receiving_run else None,
        receiving_run.phase_error_code if receiving_run else None,
    )
    tick = workspace_worker.tick()
    assert tick.previews_saved == 1
    assert repository.get_document(scope, invoice["document"]["document_id"]).document.processing_status == "ready"
    assert repository.get_document(scope, receiving["document"]["document_id"]).document.processing_status == "ready"
    detail = client.get(f"/api/workspace/documents/{invoice['document']['document_id']}").json()
    assert detail["preview"]["result"]["outcome"] == "consistent"


def test_receive_first_then_invoice_and_confirm_replay(harness):
    client, repository, worker, normalizer, scope, _storage, _factory = harness
    receiving = upload(client, "receive_note", "rn-first.pdf")
    make_ready(normalizer, receiving, "receive_note", "RN-FIRST")
    assert worker.tick().synced == 1
    assert client.get("/api/workspace/documents?type=receive_note").json()["total"] == 1

    invoice = upload(client, "invoice", "invoice-later.pdf")
    make_ready(normalizer, invoice, "invoice", "INV-LATER")
    assert worker.tick().previews_saved == 1
    document_id = invoice["document"]["document_id"]
    detail = client.get(f"/api/workspace/documents/{document_id}").json()
    command = {
        "expected_revision": detail["document"]["revision"],
        "preview_id": detail["preview"]["preview_id"],
        "acknowledged_sources": True,
        "acknowledged_unverified_dimensions": detail["preview"]["result"]["unverified_dimensions"],
        "resolution": "matched",
        "note": None,
    }
    key = uid()
    first = client.post(
        f"/api/workspace/documents/{document_id}/confirm",
        json=command,
        headers={"Idempotency-Key": key},
    )
    replay = client.post(
        f"/api/workspace/documents/{document_id}/confirm",
        json=command,
        headers={"Idempotency-Key": key},
    )
    assert first.status_code == replay.status_code == 201
    assert first.json() == replay.json()
    assert client.get(f"/api/workspace/documents/{document_id}").json()["document"]["display_status"] == "completed"
    assert repository.get_confirmation(scope, first.json()["confirmation"]["confirmation_id"]) is not None


def test_difference_investigate_resolution_and_stale_preview(harness):
    client, _repository, worker, normalizer, _scope, _storage, _factory = harness
    invoice = upload(client, "invoice", "difference.pdf")
    receiving = upload(client, "receive_note", "difference-rn.pdf")
    make_ready(normalizer, invoice, "invoice", "INV-DIFF", quantity="10")
    make_ready(normalizer, receiving, "receive_note", "RN-DIFF", quantity="8")
    assert worker.tick().previews_saved == 1
    document_id = invoice["document"]["document_id"]
    detail = client.get(f"/api/workspace/documents/{document_id}").json()
    assert detail["preview"]["result"]["outcome"] == "difference"
    revision = detail["document"]["revision"]
    response = client.post(
        f"/api/workspace/documents/{document_id}/investigate",
        json={"expected_revision": revision, "note": "Contact supplier"},
        headers={"Idempotency-Key": uid()},
    )
    assert response.status_code == 200
    detail = client.get(f"/api/workspace/documents/{document_id}").json()
    command = {
        "expected_revision": detail["document"]["revision"],
        "preview_id": detail["preview"]["preview_id"],
        "acknowledged_sources": True,
        "acknowledged_unverified_dimensions": detail["preview"]["result"]["unverified_dimensions"],
        "resolution": "resolved_with_note",
        "note": "Supplier confirmed short shipment",
    }
    confirmed = client.post(
        f"/api/workspace/documents/{document_id}/confirm",
        json=command,
        headers={"Idempotency-Key": uid()},
    )
    assert confirmed.status_code == 201
    assert confirmed.json()["confirmation"]["resolution"] == "resolved_with_note"
    first_confirmation_id = confirmed.json()["confirmation"]["confirmation_id"]

    extra = upload(client, "receive_note", "late-rn.pdf")
    make_ready(normalizer, extra, "receive_note", "RN-LATE", quantity="2")
    assert worker.tick().synced == 1
    latest = client.get(f"/api/workspace/documents/{document_id}").json()
    reopened = client.post(
        f"/api/workspace/documents/{document_id}/reopen",
        json={"expected_revision": latest["document"]["revision"], "reason": "New receiving"},
        headers={"Idempotency-Key": uid()},
    )
    assert reopened.status_code == 200
    old_snapshot = client.get(f"/api/workspace/confirmations/{first_confirmation_id}").json()
    assert old_snapshot == confirmed.json()["confirmation"]
    assert old_snapshot["confirmation_id"] == first_confirmation_id
    assert old_snapshot["receive_note_numbers"] == ["RN-DIFF"]
    assert worker.tick().previews_saved == 1
    refreshed = client.get(f"/api/workspace/documents/{document_id}").json()
    assert refreshed["preview"]["result"]["outcome"] == "consistent"
    second = client.post(
        f"/api/workspace/documents/{document_id}/confirm",
        json={
            "expected_revision": refreshed["document"]["revision"],
            "preview_id": refreshed["preview"]["preview_id"],
            "acknowledged_sources": True,
            "acknowledged_unverified_dimensions": refreshed["preview"]["result"]["unverified_dimensions"],
            "resolution": "matched",
            "note": None,
        },
        headers={"Idempotency-Key": uid()},
    )
    assert second.status_code == 201
    assert second.json()["confirmation"]["confirmation_id"] != first_confirmation_id
    assert set(second.json()["confirmation"]["receive_note_numbers"]) == {"RN-DIFF", "RN-LATE"}
    assert client.get(f"/api/workspace/confirmations/{first_confirmation_id}").json() == old_snapshot


def test_new_ready_source_rejects_stale_preview_then_recomputes(harness):
    client, _repository, worker, normalizer, _scope, _storage, _factory = harness
    invoice = upload(client, "invoice", "stale-invoice.pdf")
    receiving = upload(client, "receive_note", "stale-rn.pdf")
    extra = upload(client, "receive_note", "stale-late-rn.pdf")
    make_ready(normalizer, invoice, "invoice", "INV-STALE", quantity="10")
    make_ready(normalizer, receiving, "receive_note", "RN-STALE", quantity="8")
    assert worker.tick().previews_saved == 1
    document_id = invoice["document"]["document_id"]
    before = client.get(f"/api/workspace/documents/{document_id}").json()
    make_ready(normalizer, extra, "receive_note", "RN-STALE-LATE", quantity="2")
    response = client.post(
        f"/api/workspace/documents/{document_id}/confirm",
        json={
            "expected_revision": before["document"]["revision"],
            "preview_id": before["preview"]["preview_id"],
            "acknowledged_sources": True,
            "acknowledged_unverified_dimensions": before["preview"]["result"]["unverified_dimensions"],
            "resolution": "matched",
            "note": None,
        },
        headers={"Idempotency-Key": uid()},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "PREVIEW_STALE"
    assert worker.tick().previews_saved == 1
    refreshed = client.get(f"/api/workspace/documents/{document_id}").json()
    assert refreshed["preview"]["result"]["outcome"] == "consistent"


def test_workspace_api_source_csv_and_runtime_are_real(harness):
    client, _repository, worker, normalizer, _scope, storage, _factory = harness
    invoice = upload(client, "invoice", "dangerous invoice.pdf")
    receiving = upload(client, "receive_note", "dangerous-rn.pdf")
    make_ready(normalizer, invoice, "invoice", "=INV-CSV")
    make_ready(normalizer, receiving, "receive_note", "RN-CSV")
    assert worker.tick().previews_saved == 1
    detail = client.get(f"/api/workspace/documents/{invoice['document']['document_id']}").json()
    source = client.get(f"/api/workspace/documents/{invoice['document']['document_id']}/source")
    assert source.status_code == 200 and source.content.startswith(b"%PDF-1.7 fixture ")
    assert storage.objects
    confirmed = client.post(
        f"/api/workspace/documents/{invoice['document']['document_id']}/confirm",
        json={
            "expected_revision": detail["document"]["revision"],
            "preview_id": detail["preview"]["preview_id"],
            "acknowledged_sources": True,
            "acknowledged_unverified_dimensions": detail["preview"]["result"]["unverified_dimensions"],
            "resolution": "matched",
            "note": None,
        },
        headers={"Idempotency-Key": uid()},
    )
    assert confirmed.status_code == 201
    csv_response = client.get(
        f"/api/workspace/confirmations/{confirmed.json()['confirmation']['confirmation_id']}/export.csv"
    )
    assert csv_response.status_code == 200
    assert "'=INV-CSV" in csv_response.text
    runtime = client.get("/api/workspace/runtime")
    assert runtime.status_code == 200 and runtime.json()["enabled"] is True


def test_all_acceptance_ids_have_explicit_coverage_mapping():
    fixture = json.loads((ROOT / "tests/fixtures/workspace_scenarios.json").read_text(encoding="utf-8"))
    ids = {scenario["id"] for scenario in fixture["scenarios"]}
    assert ids == {f"A{number:02d}" for number in range(1, 31)}
    assert all(scenario["covered_by"] for scenario in fixture["scenarios"])
    for scenario in fixture["scenarios"]:
        for reference in scenario["covered_by"]:
            path, function_name = reference.split("::", 1)
            source = ast.parse((ROOT / path).read_text(encoding="utf-8"))
            functions = {
                node.name
                for node in ast.walk(source)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            assert function_name in functions, reference
