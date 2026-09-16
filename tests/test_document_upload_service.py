import pytest

from app.domain.documents import DocumentType
from app.domain.extraction_tasks import ExtractionStatus
from app.services.document_upload_service import (
    DocumentUploadService,
    DocumentValidationError,
)
from tests.fakes import InMemoryExtractionTaskRepository, InMemoryObjectStorage


def _service() -> tuple[
    DocumentUploadService,
    InMemoryObjectStorage,
    InMemoryExtractionTaskRepository,
]:
    storage = InMemoryObjectStorage()
    repository = InMemoryExtractionTaskRepository()
    return (
        DocumentUploadService(storage, repository, max_bytes=1024),
        storage,
        repository,
    )


def test_upload_persists_original_and_task() -> None:
    service, storage, repository = _service()

    task = service.upload(
        document_type=DocumentType.INVOICE,
        filename="supplier invoice.pdf",
        data=b"%PDF-1.7 test invoice",
        purchase_order_hint="PO-100",
    )

    assert task.status == ExtractionStatus.UPLOADED
    assert task.original_filename == "supplier_invoice.pdf"
    assert task.task_id in repository.tasks
    assert storage.objects[task.storage_object_key][0] == b"%PDF-1.7 test invoice"


def test_prepare_upload_writes_only_the_object() -> None:
    service, storage, repository = _service()

    prepared = service.prepare_upload(
        document_type=DocumentType.RECEIVE_NOTE,
        filename="receiving.png",
        data=b"\x89PNG\r\n\x1a\nreceiving",
    )

    assert repository.tasks == {}
    assert prepared.task.status == ExtractionStatus.UPLOADED
    assert storage.objects[prepared.task.storage_object_key][0].endswith(b"receiving")


def test_upload_preserves_repository_error_when_cleanup_also_fails() -> None:
    class FailingRepository(InMemoryExtractionTaskRepository):
        def create(self, task):
            raise RuntimeError("database failed")

    class FailingCleanupStorage(InMemoryObjectStorage):
        def delete(self, object_key: str) -> None:
            raise OSError("cleanup failed")

    service = DocumentUploadService(
        FailingCleanupStorage(), FailingRepository(), max_bytes=1024
    )

    with pytest.raises(RuntimeError, match="database failed"):
        service.upload(DocumentType.INVOICE, "invoice.pdf", b"%PDF-1.7 invoice")


@pytest.mark.parametrize(
    ("filename", "data"),
    [
        ("invoice.txt", b"not a supported document"),
        ("invoice.pdf", b"\x89PNG\r\n\x1a\ncontent"),
        ("empty.pdf", b""),
    ],
)
def test_invalid_documents_are_rejected(filename: str, data: bytes) -> None:
    service, storage, repository = _service()

    with pytest.raises(DocumentValidationError):
        service.upload(DocumentType.INVOICE, filename, data)

    assert storage.objects == {}
    assert repository.tasks == {}
