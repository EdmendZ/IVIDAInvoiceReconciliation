from decimal import Decimal

from app.domain.documents import BusinessDocument, DocumentType
from app.domain.extraction_runs import ExtractionRunStatus
from app.domain.extraction_tasks import ExtractionStatus
from app.services.document_upload_service import DocumentUploadService
from app.services.extraction_provider import ExtractionProviderResult
from app.services.extraction_service import ExtractionService
from tests.fakes import (
    InMemoryExtractionRunRepository,
    InMemoryExtractionTaskRepository,
    InMemoryObjectStorage,
)


class FixtureProvider:
    @property
    def provider_name(self) -> str:
        return "fixture"

    @property
    def model_name(self) -> str:
        return "gold-v1"

    def extract(self, **kwargs) -> ExtractionProviderResult:
        return ExtractionProviderResult(
            raw_output={"source": "fixture"},
            normalized_document=BusinessDocument.model_validate(
                {
                    "document_type": "invoice",
                    "document_number": "INV-EXTRACTED",
                    "currency": "AUD",
                    "items": [
                        {
                            "sku": "MOZZ-2",
                            "description": "Shredded mozzarella 2 kg",
                            "quantity": "2",
                            "unit_price": "28.40",
                            "line_total": "56.80",
                        }
                    ],
                }
            ),
            input_tokens=100,
            output_tokens=50,
            estimated_cost_aud=Decimal("0.0123"),
        )


def test_extraction_moves_task_to_review() -> None:
    storage = InMemoryObjectStorage()
    tasks = InMemoryExtractionTaskRepository()
    runs = InMemoryExtractionRunRepository()
    upload = DocumentUploadService(storage, tasks, max_bytes=1024)
    task = upload.upload(
        DocumentType.INVOICE,
        "invoice.pdf",
        b"%PDF-1.7 fixture",
    )
    service = ExtractionService(
        storage=storage,
        task_repository=tasks,
        run_repository=runs,
        provider=FixtureProvider(),
    )

    run = service.queue(task.task_id)
    assert tasks.get(task.task_id).status == ExtractionStatus.EXTRACTING

    service.execute(task.task_id, run.run_id)

    completed = service.get_run(run.run_id)
    assert completed.status == ExtractionRunStatus.SUCCEEDED
    assert completed.normalized_output["document_number"] == "INV-EXTRACTED"
    assert completed.estimated_cost_aud == Decimal("0.0123")
    assert tasks.get(task.task_id).status == ExtractionStatus.READY_FOR_REVIEW
