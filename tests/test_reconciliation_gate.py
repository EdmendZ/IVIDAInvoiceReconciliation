from datetime import UTC, datetime

import pytest

from app.domain.document_versions import (
    DocumentVersion,
    DocumentVersionStatus,
)
from app.domain.documents import DocumentType
from app.services.reconciliation_application_service import (
    DocumentNotApproved,
    ReconciliationApplicationService,
)


class VersionReader:
    def __init__(self, versions: list[DocumentVersion]) -> None:
        self.versions = {item.version_id: item for item in versions}

    def get_approved_version(self, version_id: str):
        version = self.versions.get(version_id)
        if version and version.status == DocumentVersionStatus.APPROVED:
            return version
        return None


class RecordWriter:
    def __init__(self) -> None:
        self.records = []

    def create(self, record):
        self.records.append(record)
        return record


def _version(
    version_id: str,
    document_type: DocumentType,
    status: DocumentVersionStatus,
) -> DocumentVersion:
    payload = {
        "document_type": document_type.value,
        "document_number": (
            "INV-1" if document_type == DocumentType.INVOICE else "RN-1"
        ),
        "purchase_order_number": "PO-1",
        "items": [
            {
                "sku": "CHEESE",
                "description": "Mozzarella",
                "quantity": "2",
                "unit_price": "10.00",
                "line_total": "20.00",
            }
        ],
    }
    return DocumentVersion(
        version_id=version_id,
        task_id=f"task-{version_id}",
        source_draft_id=f"draft-{version_id}",
        version_number=1,
        document_type=document_type,
        document_json=payload,
        status=status,
        created_by="user-1",
        approved_by="user-1" if status == DocumentVersionStatus.APPROVED else None,
        approved_at=(
            datetime.now(UTC)
            if status == DocumentVersionStatus.APPROVED
            else None
        ),
        created_at=datetime.now(UTC),
    )


def test_draft_invoice_is_rejected() -> None:
    invoice = _version(
        "invoice-draft",
        DocumentType.INVOICE,
        DocumentVersionStatus.DRAFT,
    )
    note = _version(
        "note-approved",
        DocumentType.RECEIVE_NOTE,
        DocumentVersionStatus.APPROVED,
    )
    service = ReconciliationApplicationService(
        review_repository=VersionReader([invoice, note]),
        reconciliation_repository=RecordWriter(),
    )
    with pytest.raises(DocumentNotApproved):
        service.compare(
            invoice.version_id,
            [note.version_id],
            created_by="user-1",
        )


def test_approved_versions_create_persistent_result() -> None:
    invoice = _version(
        "invoice-approved",
        DocumentType.INVOICE,
        DocumentVersionStatus.APPROVED,
    )
    note = _version(
        "note-approved",
        DocumentType.RECEIVE_NOTE,
        DocumentVersionStatus.APPROVED,
    )
    writer = RecordWriter()
    service = ReconciliationApplicationService(
        review_repository=VersionReader([invoice, note]),
        reconciliation_repository=writer,
    )
    record = service.compare(
        invoice.version_id,
        [note.version_id],
        created_by="user-1",
    )
    assert record.invoice_version_id == invoice.version_id
    assert record.result.summary.total_lines == 1
    assert record.result.summary.requires_review is False
    assert writer.records == [record]
