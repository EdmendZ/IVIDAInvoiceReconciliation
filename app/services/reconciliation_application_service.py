from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from app.domain.document_versions import DocumentVersion
from app.domain.documents import DocumentType, Invoice, ReceiveNote
from app.domain.reconciliation import (
    ReconciliationRequest,
    ReconciliationTolerance,
)
from app.domain.reconciliation_records import ReconciliationRecord
from app.services.reconciliation_service import reconcile


class DocumentNotApproved(RuntimeError):
    pass


class ApprovedVersionReader(Protocol):
    def get_approved_version(self, version_id: str) -> DocumentVersion | None: ...


class ReconciliationWriter(Protocol):
    def create(self, record: ReconciliationRecord) -> ReconciliationRecord: ...


class ReconciliationApplicationService:
    def __init__(
        self,
        *,
        review_repository: ApprovedVersionReader,
        reconciliation_repository: ReconciliationWriter,
    ) -> None:
        self._reviews = review_repository
        self._reconciliations = reconciliation_repository

    def compare(
        self,
        approved_invoice_version_id: str,
        approved_receive_note_version_ids: list[str],
        *,
        created_by: str,
        tolerance: ReconciliationTolerance | None = None,
    ) -> ReconciliationRecord:
        if not approved_receive_note_version_ids:
            raise ValueError("At least one Receive Note version is required")
        invoice_version = self._require_approved(
            approved_invoice_version_id,
            DocumentType.INVOICE,
        )
        note_versions = [
            self._require_approved(version_id, DocumentType.RECEIVE_NOTE)
            for version_id in approved_receive_note_version_ids
        ]
        result = reconcile(
            ReconciliationRequest(
                invoice=Invoice.model_validate(invoice_version.document_json),
                receive_notes=[
                    ReceiveNote.model_validate(version.document_json)
                    for version in note_versions
                ],
                tolerance=tolerance or ReconciliationTolerance(),
            )
        )
        return self._reconciliations.create(
            ReconciliationRecord(
                reconciliation_id=str(uuid4()),
                invoice_version_id=invoice_version.version_id,
                receive_note_version_ids=[
                    version.version_id for version in note_versions
                ],
                result=result,
                created_by=created_by,
                created_at=datetime.now(UTC),
            )
        )

    def _require_approved(
        self,
        version_id: str,
        expected_type: DocumentType,
    ) -> DocumentVersion:
        version = self._reviews.get_approved_version(version_id)
        if version is None or version.document_type != expected_type:
            raise DocumentNotApproved(
                f"{expected_type.value} version is not approved"
            )
        return version
