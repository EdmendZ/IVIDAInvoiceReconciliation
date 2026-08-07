from collections.abc import Iterator
from contextlib import contextmanager

from fastapi.testclient import TestClient

from app.api.dependencies import get_document_upload_service
from app.main import app
from app.services.document_upload_service import DocumentUploadService
from tests.auth_helpers import restore_override, reviewer_client
from tests.fakes import InMemoryExtractionTaskRepository, InMemoryObjectStorage


@contextmanager
def upload_client() -> Iterator[TestClient]:
    service = DocumentUploadService(
        InMemoryObjectStorage(),
        InMemoryExtractionTaskRepository(),
        max_bytes=1024,
    )
    previous = app.dependency_overrides.get(get_document_upload_service)
    app.dependency_overrides[get_document_upload_service] = lambda: service
    try:
        with reviewer_client(app) as client:
            yield client
    finally:
        restore_override(app, get_document_upload_service, previous)


def test_upload_and_get_task() -> None:
    with upload_client() as client:
        response = client.post(
            "/api/documents/upload",
            data={
                "document_type": "receive_note",
                "purchase_order_hint": "PO-200",
            },
            files={"file": ("rn-1.png", b"\x89PNG\r\n\x1a\nimage", "image/png")},
        )

        assert response.status_code == 201
        task = response.json()
        assert task["document_type"] == "receive_note"
        assert task["status"] == "uploaded"

        get_response = client.get(f"/api/extraction-tasks/{task['task_id']}")
        assert get_response.status_code == 200
        assert get_response.json()["sha256"] == task["sha256"]


def test_missing_task_returns_404() -> None:
    with upload_client() as client:
        response = client.get("/api/extraction-tasks/missing")

        assert response.status_code == 404
