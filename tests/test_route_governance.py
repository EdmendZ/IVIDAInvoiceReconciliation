from fastapi.testclient import TestClient
import pytest

from app.main import app


def test_upload_requires_reviewer() -> None:
    response = TestClient(app).post(
        "/api/documents/upload",
        data={"document_type": "invoice"},
        files={
            "file": (
                "invoice.pdf",
                b"%PDF-1.4\n",
                "application/pdf",
            )
        },
    )

    assert response.status_code == 401


def test_task_lookup_requires_reviewer() -> None:
    response = TestClient(app).get("/api/extraction-tasks/task-1")

    assert response.status_code == 401


def test_extraction_start_and_result_require_reviewer() -> None:
    client = TestClient(app)

    assert client.post("/api/extraction-tasks/task-1/extract").status_code == 401
    assert client.get("/api/extraction-runs/run-1").status_code == 401
    assert client.get("/api/extraction-runs/run-1/result").status_code == 401
    assert client.post("/api/extraction-runs/run-1/cancel").status_code == 401


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/reconciliation-cases"),
        ("get", "/api/reconciliation-cases/case-1"),
        ("post", "/api/reconciliation-cases/case-1/claim"),
        ("post", "/api/reconciliation-cases/case-1/reassign"),
        ("put", "/api/reconciliation-cases/case-1/items/item-1/resolution"),
        ("post", "/api/reconciliation-cases/case-1/submit-approval"),
        ("post", "/api/reconciliation-cases/case-1/submit-void"),
        ("post", "/api/reconciliation-cases/case-1/approve"),
        ("post", "/api/reconciliation-cases/case-1/return"),
        ("post", "/api/reconciliation-cases/case-1/void"),
    ],
)
def test_case_routes_require_authentication(method: str, path: str) -> None:
    response = TestClient(app).request(
        method.upper(),
        path,
        json={"expected_revision": 1},
    )

    assert response.status_code == 401


def test_case_assignee_route_requires_authentication() -> None:
    assert TestClient(app).get(
        "/api/reconciliation-cases/assignees"
    ).status_code == 401
