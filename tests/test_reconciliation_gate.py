from datetime import UTC, datetime

import pytest

from app.domain.document_versions import (
    DocumentVersion,
    DocumentVersionStatus,
)
from app.domain.document_sources import DocumentSourceKind, DocumentTrustMethod
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

    def list_versions(self, *, status=None):
        return [
            version
            for version in self.versions.values()
            if status is None or version.status == status
        ]

    def list_reconciliation_versions(self):
        return [
            version
            for version in self.versions.values()
            if version.status == DocumentVersionStatus.APPROVED
        ]


class RecordWriter:
    def __init__(self) -> None:
        self.bundles = []

    @property
    def records(self):
        return [bundle.record for bundle in self.bundles]

    def create(self, bundle):
        self.bundles.append(bundle)
        return bundle.record

    def get(self, reconciliation_id):
        return next(
            (
                record
                for record in self.records
                if record.reconciliation_id == reconciliation_id
            ),
            None,
        )


def _version(
    version_id: str,
    document_type: DocumentType,
    status: DocumentVersionStatus,
    *,
    quantity: str = "2",
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
                "quantity": quantity,
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
        source_kind=(
            DocumentSourceKind.INVOICE_UPLOAD
            if document_type == DocumentType.INVOICE
            else DocumentSourceKind.EXTERNAL_RECEIVE_NOTE_UPLOAD
        ),
        trust_method=(
            DocumentTrustMethod.HUMAN_APPROVED
            if status == DocumentVersionStatus.APPROVED
            else DocumentTrustMethod.UNTRUSTED
        ),
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
    assert len(writer.bundles[0].line_result_ids) == len(record.result.lines)
    assert writer.bundles[0].case is None
    assert service.get_record(record.reconciliation_id) == record


def test_abnormal_compare_builds_case_with_preallocated_line_ids() -> None:
    invoice = _version(
        "invoice-approved",
        DocumentType.INVOICE,
        DocumentVersionStatus.APPROVED,
    )
    note = _version(
        "note-approved",
        DocumentType.RECEIVE_NOTE,
        DocumentVersionStatus.APPROVED,
        quantity="1",
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

    bundle = writer.bundles[0]
    assert bundle.record == record
    assert len(bundle.line_result_ids) == len(record.result.lines)
    assert len(set(bundle.line_result_ids)) == len(bundle.line_result_ids)
    assert bundle.case is not None
    assert bundle.case.items[0].line_result_id == bundle.line_result_ids[0]
    assert "line_result_ids" not in type(record.result).model_fields


def test_candidates_only_include_approved_receive_notes() -> None:
    invoice = _version(
        "invoice-approved",
        DocumentType.INVOICE,
        DocumentVersionStatus.APPROVED,
    )
    approved_note = _version(
        "note-approved",
        DocumentType.RECEIVE_NOTE,
        DocumentVersionStatus.APPROVED,
    )
    draft_note = _version(
        "note-draft",
        DocumentType.RECEIVE_NOTE,
        DocumentVersionStatus.DRAFT,
    )
    service = ReconciliationApplicationService(
        review_repository=VersionReader([invoice, approved_note, draft_note]),
        reconciliation_repository=RecordWriter(),
    )

    candidates = service.list_candidates(invoice.version_id)

    assert [item.receive_note_version_id for item in candidates] == [
        approved_note.version_id
    ]
