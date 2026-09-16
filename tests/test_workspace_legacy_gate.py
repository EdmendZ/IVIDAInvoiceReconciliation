from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app.api.dependencies as dependency_module
from app.api.auth_dependencies import require_reviewer
from app.api.dependencies import require_legacy_mutation_available
from app.main import app
from tests.auth_helpers import TEST_REVIEWER, restore_override


LEGACY_MUTATIONS = [
    (
        "POST",
        "/api/documents/upload",
        {
            "data": {"document_type": "invoice"},
            "files": {
                "file": ("invoice.pdf", b"%PDF-1.7 body", "application/pdf")
            },
        },
    ),
    ("POST", "/api/extraction-tasks/task-id/extract", {}),
    ("POST", "/api/extraction-runs/run-id/cancel", {}),
    ("POST", "/api/review/tasks/task-id/start", {}),
    (
        "PATCH",
        "/api/review/versions/version-id",
        {"json": {"document": {}, "reason": "correction"}},
    ),
    (
        "POST",
        "/api/review/versions/version-id/reclassify",
        {"json": {"document_type": "invoice", "reason": "correction"}},
    ),
    (
        "POST",
        "/api/review/versions/version-id/approve",
        {"json": {"confirmed_document_type": "invoice", "reason": "approved"}},
    ),
    (
        "POST",
        "/api/review/versions/version-id/reject",
        {"json": {"reason": "rejected"}},
    ),
    (
        "POST",
        "/api/reconciliations",
        {
            "json": {
                "invoice_version_id": "invoice-version",
                "receive_note_version_ids": ["receive-version"],
            }
        },
    ),
    (
        "POST",
        "/api/reconciliation-cases/case-id/claim",
        {"json": {"expected_revision": 1}},
    ),
    (
        "POST",
        "/api/reconciliation-cases/case-id/reassign",
        {
            "json": {
                "assignee_user_id": TEST_REVIEWER.user_id,
                "reason": "balance queue",
                "expected_revision": 1,
            }
        },
    ),
    (
        "PUT",
        "/api/reconciliation-cases/case-id/items/item-id/resolution",
        {
            "json": {
                "resolution_type": "business_exception",
                "note": "supplier confirmed",
                "expected_revision": 1,
            }
        },
    ),
    (
        "POST",
        "/api/reconciliation-cases/case-id/submit-approval",
        {"json": {"expected_revision": 1}},
    ),
    (
        "POST",
        "/api/reconciliation-cases/case-id/submit-void",
        {"json": {"expected_revision": 1}},
    ),
    (
        "POST",
        "/api/reconciliation-cases/case-id/approve",
        {"json": {"expected_revision": 1}},
    ),
    (
        "POST",
        "/api/reconciliation-cases/case-id/return",
        {"json": {"reason": "clarify", "expected_revision": 1}},
    ),
    (
        "POST",
        "/api/reconciliation-cases/case-id/void",
        {"json": {"expected_revision": 1}},
    ),
]


@pytest.mark.parametrize(("method", "path", "kwargs"), LEGACY_MUTATIONS)
def test_workspace_enabled_rejects_every_legacy_mutation(
    monkeypatch, method: str, path: str, kwargs: dict
) -> None:
    monkeypatch.setattr(
        dependency_module,
        "get_settings",
        lambda: SimpleNamespace(workspace_enabled=True),
    )
    previous = app.dependency_overrides.get(require_reviewer)
    app.dependency_overrides[require_reviewer] = lambda: TEST_REVIEWER
    try:
        response = TestClient(app).request(method, path, **kwargs)
    finally:
        restore_override(app, require_reviewer, previous)

    assert response.status_code == 409, response.text
    assert response.json() == {
        "detail": {
            "code": "LEGACY_READ_ONLY",
            "message": "工作台已启用，旧流程仅供查询",
        }
    }


def test_workspace_disabled_keeps_legacy_gate_transparent(monkeypatch) -> None:
    monkeypatch.setattr(
        dependency_module,
        "get_settings",
        lambda: SimpleNamespace(workspace_enabled=False),
    )
    assert require_legacy_mutation_available(TEST_REVIEWER) == TEST_REVIEWER
