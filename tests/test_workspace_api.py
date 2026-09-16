import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app.api.dependencies as dependency_module
import app.api.workspace_routes as workspace_routes
from app.api.auth_dependencies import get_auth_service, require_reviewer
from app.api.dependencies import get_workspace_runtime_service, get_workspace_service
from app.domain.documents import DocumentType
from app.domain.workspace import (
    ActionPage,
    ConfirmationResponse,
    ConfirmationView,
    Coverage,
    DisplayStatus,
    DocumentDetail,
    DocumentPage,
    DocumentSummary,
    IntakeResponse,
    MatchStatus,
    PreviewOutcome,
    PreviewResult,
    PreviewSummary,
    ProcessingStatus,
    Resolution,
    RetryResponse,
    RuntimeView,
    SourceFile,
    SourceKind,
    SubjectComparison,
    WorkspaceError,
    WorkspaceErrorCode,
)
from app.main import app
from tests.auth_helpers import TEST_REVIEWER, restore_override


def uid(number: int) -> str:
    return f"00000000-0000-0000-0000-{number:012d}"


NOW = datetime(2026, 9, 16, tzinfo=UTC)
DOCUMENT_ID = uid(1)
CONFIRMATION_ID = uid(2)
KEY = uid(99)


def summary() -> DocumentSummary:
    return DocumentSummary(
        document_id=DOCUMENT_ID,
        document_type=DocumentType.INVOICE,
        source_kind=SourceKind.UPLOAD,
        revision=1,
        processing_status=ProcessingStatus.READY,
        display_status=DisplayStatus.WAITING_COUNTERPART,
        updated_at=NOW,
    )


def result() -> PreviewResult:
    return PreviewResult(
        outcome=PreviewOutcome.CONSISTENT,
        coverage=Coverage.QUANTITY_ONLY,
        unverified_dimensions=["document_total", "tax"],
        summary=PreviewSummary(
            total_lines=0,
            different_lines=0,
            unverified_lines=0,
        ),
        subject=SubjectComparison(
            supplier="equal",
            currency="equal",
            scope="equal",
        ),
    )


def confirmation() -> ConfirmationView:
    return ConfirmationView(
        confirmation_id=CONFIRMATION_ID,
        preview_id=uid(3),
        invoice_number="INV-1",
        receive_note_numbers=["RN-1"],
        resolution=Resolution.MATCHED,
        acknowledged_unverified_dimensions=["document_total", "tax"],
        result_snapshot=result(),
        input_revision_ids=[uid(4), uid(5)],
        actor_id=TEST_REVIEWER.user_id,
        created_at=NOW,
    )


class RecordingWorkspaceService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple]] = []
        self.error: Exception | None = None

    def _return(self, name: str, args: tuple, value):
        self.calls.append((name, args))
        if self.error is not None:
            raise self.error
        return value

    def upload(self, *args):
        return self._return(
            "upload",
            args,
            IntakeResponse(
                document=summary(), task_id=uid(6), run_id=uid(7), duplicate=False
            ),
        )

    def list_documents(self, *args):
        return self._return(
            "list_documents",
            args,
            DocumentPage(items=[summary()], page=1, page_size=20, total=1),
        )

    def get_document(self, *args):
        return self._return(
            "get_document",
            args,
            DocumentDetail(
                document=summary(),
                match_status=MatchStatus.WAITING_COUNTERPART,
                preview_stale=False,
                source_url_available=True,
            ),
        )

    def source(self, *args):
        return self._return(
            "source",
            args,
            SourceFile(
                filename="invoice.pdf",
                content_type="application/pdf",
                data=b"%PDF-1.7 original",
            ),
        )

    def get_actions(self, *args):
        return self._return(
            "get_actions",
            args,
            ActionPage(items=[], page=1, page_size=20, total=0),
        )

    def edit(self, *args):
        return self._return("edit", args, summary())

    def select(self, *args):
        return self._return("select", args, summary())

    def investigate(self, *args):
        return self._return("investigate", args, summary())

    def confirm(self, *args):
        return self._return(
            "confirm",
            args,
            ConfirmationResponse(document=summary(), confirmation=confirmation()),
        )

    def reopen(self, *args):
        return self._return("reopen", args, summary())

    def void(self, *args):
        return self._return("void", args, summary())

    def retry(self, *args):
        return self._return(
            "retry", args, RetryResponse(document=summary(), run_id=uid(8))
        )

    def get_confirmation(self, *args):
        return self._return("get_confirmation", args, confirmation())

    def export(self, *args):
        return self._return("export", args, "\ufeffconfirmation_id\r\nvalue\r\n")

    def runtime(self, *args):
        return self._return(
            "runtime",
            args,
            RuntimeView(
                enabled=True,
                worker_online=True,
                last_sync_at=NOW,
                preview_lag_seconds=0,
            ),
        )


@pytest.fixture
def workspace_client(monkeypatch):
    service = RecordingWorkspaceService()
    settings = SimpleNamespace(workspace_enabled=True, upload_max_bytes=1024)
    monkeypatch.setattr(dependency_module, "get_settings", lambda: settings)
    monkeypatch.setattr(workspace_routes, "get_settings", lambda: settings)
    previous_user = app.dependency_overrides.get(require_reviewer)
    previous_service = app.dependency_overrides.get(get_workspace_service)
    previous_runtime = app.dependency_overrides.get(get_workspace_runtime_service)
    app.dependency_overrides[require_reviewer] = lambda: TEST_REVIEWER
    app.dependency_overrides[get_workspace_service] = lambda: service
    app.dependency_overrides[get_workspace_runtime_service] = lambda: service
    try:
        with TestClient(app) as client:
            yield client, service
    finally:
        restore_override(app, require_reviewer, previous_user)
        restore_override(app, get_workspace_service, previous_service)
        restore_override(app, get_workspace_runtime_service, previous_runtime)


def invoice_payload() -> dict:
    return {
        "document_type": "invoice",
        "document_number": "INV-1",
        "currency": "AUD",
        "items": [
            {
                "description": "Flour",
                "quantity": "1",
                "unit": "bag",
                "unit_price": "10.00",
                "line_total": "10.00",
            }
        ],
    }


def test_openapi_matches_every_frozen_workspace_route() -> None:
    contract = json.loads(Path("spec/contracts.json").read_text(encoding="utf-8"))
    schema = app.openapi()
    expected = {
        (route["method"], contract["prefix"] + route["path"]): route
        for route in contract["routes"]
    }
    actual = {
        (method.upper(), path): operation
        for path, operations in schema["paths"].items()
        if path.startswith(contract["prefix"])
        for method, operation in operations.items()
        if method in {"get", "post", "put", "patch"}
    }

    assert set(actual) == set(expected)
    for key, route in expected.items():
        operation = actual[key]
        assert str(route["success_status"]) in operation["responses"]
        header_names = {
            parameter["name"]
            for parameter in operation.get("parameters", [])
            if parameter["in"] == "header"
        }
        assert ("Idempotency-Key" in header_names) is route[
            "idempotency_key_required"
        ]


def test_all_routes_delegate_with_frozen_statuses_and_safe_download_headers(
    workspace_client,
) -> None:
    client, service = workspace_client
    headers = {"Idempotency-Key": KEY}
    common = {"expected_revision": 1}
    calls = [
        (
            "POST",
            "/api/workspace/documents",
            {"data": {"document_type": "invoice"}, "files": {"file": ("invoice.pdf", b"%PDF-1.7 body", "application/pdf")}, "headers": headers},
            201,
            "upload",
        ),
        ("GET", "/api/workspace/documents", {}, 200, "list_documents"),
        ("GET", f"/api/workspace/documents/{DOCUMENT_ID}", {}, 200, "get_document"),
        ("GET", f"/api/workspace/documents/{DOCUMENT_ID}/source", {}, 200, "source"),
        ("GET", f"/api/workspace/documents/{DOCUMENT_ID}/actions", {}, 200, "get_actions"),
        ("PATCH", f"/api/workspace/documents/{DOCUMENT_ID}", {"json": {**common, "document": invoice_payload(), "reason": "Correct fields"}, "headers": headers}, 200, "edit"),
        ("PUT", f"/api/workspace/documents/{DOCUMENT_ID}/selection", {"json": {**common, "receive_document_ids": [uid(10)], "reason": "Checked source"}, "headers": headers}, 200, "select"),
        ("POST", f"/api/workspace/documents/{DOCUMENT_ID}/investigate", {"json": {**common, "note": "Check difference"}, "headers": headers}, 200, "investigate"),
        ("POST", f"/api/workspace/documents/{DOCUMENT_ID}/confirm", {"json": {**common, "preview_id": uid(3), "acknowledged_sources": True, "acknowledged_unverified_dimensions": ["document_total", "tax"], "resolution": "matched", "note": None}, "headers": headers}, 201, "confirm"),
        ("POST", f"/api/workspace/documents/{DOCUMENT_ID}/reopen", {"json": {**common, "reason": "New receiving"}, "headers": headers}, 200, "reopen"),
        ("POST", f"/api/workspace/documents/{DOCUMENT_ID}/void", {"json": {**common, "reason": "Duplicate upload"}, "headers": headers}, 200, "void"),
        ("POST", f"/api/workspace/documents/{DOCUMENT_ID}/retry", {"json": common, "headers": headers}, 202, "retry"),
        ("GET", f"/api/workspace/confirmations/{CONFIRMATION_ID}", {}, 200, "get_confirmation"),
        ("GET", f"/api/workspace/confirmations/{CONFIRMATION_ID}/export.csv", {}, 200, "export"),
        ("GET", "/api/workspace/runtime", {}, 200, "runtime"),
    ]

    for method, path, kwargs, expected_status, expected_call in calls:
        response = client.request(method, path, **kwargs)
        assert response.status_code == expected_status, response.text
        assert service.calls[-1][0] == expected_call
        if expected_call == "source":
            assert response.content == b"%PDF-1.7 original"
            assert response.headers["cache-control"] == "private, no-store"
            assert response.headers["x-content-type-options"] == "nosniff"
            assert response.headers["content-disposition"].startswith("inline;")
        if expected_call == "export":
            assert response.content.startswith(b"\xef\xbb\xbf")
            assert response.headers["cache-control"] == "private, no-store"
            assert response.headers["x-content-type-options"] == "nosniff"


def test_mutations_require_uuid_idempotency_header(workspace_client) -> None:
    client, service = workspace_client
    response = client.post(
        f"/api/workspace/documents/{DOCUMENT_ID}/retry",
        json={"expected_revision": 1},
        headers={"Idempotency-Key": "not-a-uuid"},
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": {"code": "INVALID_REQUEST", "message": "请求参数格式不正确"}
    }
    assert service.calls == []


def test_upload_rejects_scope_and_other_extra_form_fields(workspace_client) -> None:
    client, service = workspace_client
    response = client.post(
        "/api/workspace/documents",
        data={"document_type": "invoice", "tenant_id": "other"},
        files={"file": ("invoice.pdf", b"%PDF-1.7 body", "application/pdf")},
        headers={"Idempotency-Key": KEY},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "INVALID_REQUEST"
    assert service.calls == []


@pytest.mark.parametrize("note", [None, "   ", "x" * 2001])
def test_confirm_note_validation_uses_frozen_domain_error(
    workspace_client, note: str | None
) -> None:
    client, service = workspace_client
    response = client.post(
        f"/api/workspace/documents/{DOCUMENT_ID}/confirm",
        json={
            "expected_revision": 1,
            "preview_id": uid(3),
            "acknowledged_sources": True,
            "acknowledged_unverified_dimensions": ["document_total", "tax"],
            "resolution": "resolved_with_note",
            "note": note,
        },
        headers={"Idempotency-Key": KEY},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "RESOLUTION_NOTE_REQUIRED"
    assert service.calls == []


def test_confirm_duplicate_acknowledgements_use_frozen_domain_error(
    workspace_client,
) -> None:
    client, service = workspace_client
    response = client.post(
        f"/api/workspace/documents/{DOCUMENT_ID}/confirm",
        json={
            "expected_revision": 1,
            "preview_id": uid(3),
            "acknowledged_sources": True,
            "acknowledged_unverified_dimensions": ["tax", "tax"],
            "resolution": "matched",
            "note": None,
        },
        headers={"Idempotency-Key": KEY},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "UNVERIFIED_NOT_ACKNOWLEDGED"
    assert service.calls == []


def test_confirm_requires_source_acknowledgement_with_frozen_domain_error(
    workspace_client,
) -> None:
    client, service = workspace_client
    response = client.post(
        f"/api/workspace/documents/{DOCUMENT_ID}/confirm",
        json={
            "expected_revision": 1,
            "preview_id": uid(3),
            "acknowledged_sources": False,
            "acknowledged_unverified_dimensions": ["document_total", "tax"],
            "resolution": "matched",
            "note": None,
        },
        headers={"Idempotency-Key": KEY},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "UNVERIFIED_NOT_ACKNOWLEDGED"
    assert service.calls == []


def test_domain_database_and_unexpected_errors_are_safe(workspace_client) -> None:
    client, service = workspace_client
    service.error = WorkspaceError(
        WorkspaceErrorCode.REVISION_CONFLICT,
        "单据已更新，请查看最新内容",
        document_id=DOCUMENT_ID,
        current_revision=7,
    )
    conflict = client.get(f"/api/workspace/documents/{DOCUMENT_ID}")
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == {
        "code": "REVISION_CONFLICT",
        "message": "单据已更新，请查看最新内容",
        "document_id": DOCUMENT_ID,
        "current_revision": 7,
    }

    service.error = RuntimeError("password=secret; SELECT * FROM private_table")
    failed = client.get(f"/api/workspace/documents/{DOCUMENT_ID}")
    assert failed.status_code == 500
    assert failed.json()["detail"] == {
        "code": "INTERNAL_ERROR",
        "message": "工作台处理请求时发生内部错误",
    }
    assert failed.headers.get("x-request-id")
    assert "secret" not in failed.text
    assert "SELECT" not in failed.text


class NoAuthentication:
    def authenticate(self, token: str):
        del token
        return None


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/workspace/documents"),
        ("GET", "/api/workspace/documents"),
        ("GET", f"/api/workspace/documents/{DOCUMENT_ID}"),
        ("GET", f"/api/workspace/documents/{DOCUMENT_ID}/source"),
        ("GET", f"/api/workspace/documents/{DOCUMENT_ID}/actions"),
        ("PATCH", f"/api/workspace/documents/{DOCUMENT_ID}"),
        ("PUT", f"/api/workspace/documents/{DOCUMENT_ID}/selection"),
        ("POST", f"/api/workspace/documents/{DOCUMENT_ID}/investigate"),
        ("POST", f"/api/workspace/documents/{DOCUMENT_ID}/confirm"),
        ("POST", f"/api/workspace/documents/{DOCUMENT_ID}/reopen"),
        ("POST", f"/api/workspace/documents/{DOCUMENT_ID}/void"),
        ("POST", f"/api/workspace/documents/{DOCUMENT_ID}/retry"),
        ("GET", f"/api/workspace/confirmations/{CONFIRMATION_ID}"),
        ("GET", f"/api/workspace/confirmations/{CONFIRMATION_ID}/export.csv"),
        ("GET", "/api/workspace/runtime"),
    ],
)
def test_every_workspace_route_requires_session_before_scope_or_body_validation(
    method: str, path: str
) -> None:
    previous = app.dependency_overrides.get(get_auth_service)
    app.dependency_overrides[get_auth_service] = NoAuthentication
    try:
        response = TestClient(app).request(method, path)
    finally:
        restore_override(app, get_auth_service, previous)

    assert response.status_code == 401
    assert response.json() == {
        "detail": {"code": "AUTH_REQUIRED", "message": "请先登录后再访问工作台"}
    }
    assert response.headers["www-authenticate"] == "Session"


def test_disabled_runtime_needs_auth_but_not_scope_and_writes_are_409() -> None:
    previous = app.dependency_overrides.get(require_reviewer)
    app.dependency_overrides[require_reviewer] = lambda: TEST_REVIEWER
    try:
        client = TestClient(app)
        runtime = client.get("/api/workspace/runtime")
        write = client.post(
            f"/api/workspace/documents/{DOCUMENT_ID}/retry",
            json={"expected_revision": 1},
            headers={"Idempotency-Key": KEY},
        )
        read = client.get("/api/workspace/documents")
    finally:
        restore_override(app, require_reviewer, previous)

    assert runtime.status_code == 200
    assert runtime.json() == {
        "enabled": False,
        "worker_online": False,
        "last_sync_at": None,
        "preview_lag_seconds": None,
    }
    assert write.status_code == 409
    assert write.json()["detail"]["code"] == "INVALID_TRANSITION"
    assert read.status_code == 503
    assert read.json()["detail"]["code"] == "WORKSPACE_UNAVAILABLE"


def test_unknown_workspace_path_uses_safe_structured_404() -> None:
    previous = app.dependency_overrides.get(require_reviewer)
    app.dependency_overrides[require_reviewer] = lambda: TEST_REVIEWER
    try:
        response = TestClient(app).get("/api/workspace/not-a-route")
    finally:
        restore_override(app, require_reviewer, previous)

    assert response.status_code == 404
    assert response.json() == {
        "detail": {
            "code": "DOCUMENT_NOT_FOUND",
            "message": "未找到请求的记录",
        }
    }
