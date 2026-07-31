from fastapi.testclient import TestClient

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
