from decimal import Decimal

from fastapi.testclient import TestClient

from app.api.dependencies import get_document_upload_service, get_extraction_service
from app.domain.documents import BusinessDocument
from app.main import app
from app.services.document_upload_service import DocumentUploadService
from app.services.extraction_provider import ExtractionProviderResult
from app.services.extraction_service import ExtractionService
from tests.fakes import (
    InMemoryExtractionRunRepository,
    InMemoryExtractionTaskRepository,
    InMemoryObjectStorage,
)


class ApiFixtureProvider:
    @property
    def provider_name(self) -> str:
        return "api-fixture"

    @property
    def model_name(self) -> str:
        return "gold-v1"

    def extract(self, **kwargs) -> ExtractionProviderResult:
        document_type = kwargs["document_type"].value
        return ExtractionProviderResult(
            raw_output={"source": "api-fixture"},
            normalized_document=BusinessDocument.model_validate(
                {
                    "document_type": document_type,
                    "document_number": "API-EXTRACTED-1",
                    "currency": "AUD",
                    "items": [
                        {
                            "sku": "FLOUR-12.5",
                            "description": "Pizza flour 12.5 kg",
                            "quantity": "8",
                            "unit_price": "22.50",
                            "line_total": "180.00",
                        }
                    ],
                }
            ),
            estimated_cost_aud=Decimal("0"),
        )


def test_start_and_query_extraction() -> None:
    storage = InMemoryObjectStorage()
    tasks = InMemoryExtractionTaskRepository()
    runs = InMemoryExtractionRunRepository()
    upload_service = DocumentUploadService(storage, tasks, max_bytes=1024)
    extraction_service = ExtractionService(
        storage=storage,
        task_repository=tasks,
        run_repository=runs,
        provider=ApiFixtureProvider(),
    )
    previous_upload = app.dependency_overrides.get(get_document_upload_service)
    previous_extraction = app.dependency_overrides.get(get_extraction_service)
    app.dependency_overrides[get_document_upload_service] = lambda: upload_service
    app.dependency_overrides[get_extraction_service] = lambda: extraction_service
    client = TestClient(app)
    try:
        upload_response = client.post(
            "/api/documents/upload",
            data={"document_type": "invoice"},
            files={"file": ("invoice.pdf", b"%PDF-1.7 fixture", "application/pdf")},
        )
        task_id = upload_response.json()["task_id"]

        start_response = client.post(f"/api/extraction-tasks/{task_id}/extract")

        assert start_response.status_code == 202
        run_id = start_response.json()["run_id"]
        run_response = client.get(f"/api/extraction-runs/{run_id}")
        task_response = client.get(f"/api/extraction-tasks/{task_id}")
        assert run_response.status_code == 200
        assert run_response.json()["status"] == "succeeded"
        assert (
            run_response.json()["normalized_output"]["document_number"]
            == "API-EXTRACTED-1"
        )
        assert task_response.json()["status"] == "ready_for_review"
    finally:
        if previous_upload is None:
            app.dependency_overrides.pop(get_document_upload_service, None)
        else:
            app.dependency_overrides[get_document_upload_service] = previous_upload
        if previous_extraction is None:
            app.dependency_overrides.pop(get_extraction_service, None)
        else:
            app.dependency_overrides[get_extraction_service] = previous_extraction
