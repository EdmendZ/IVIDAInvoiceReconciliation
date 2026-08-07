"""Map a Taptouch receiving snapshot into the canonical document version store."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from pydantic import BaseModel

from app.domain.document_sources import DocumentSourceKind, DocumentTrustMethod
from app.domain.document_versions import DocumentVersion, DocumentVersionStatus
from app.domain.documents import DocumentType, ReceiveNote
from app.domain.taptouch_receiving import TaptouchReceivingPayload


class ReceivingVersionConflict(RuntimeError):
    """The caller supplied an external version older than the stored latest version."""


class ReceivingIdentityConflict(RuntimeError):
    """The same external version identity was reused for different content."""


class ReceivingImportOutcome(BaseModel):
    version: DocumentVersion
    created: bool


class TaptouchReceivingImportRepository(Protocol):
    def import_version(self, version: DocumentVersion) -> ReceivingImportOutcome: ...


class TaptouchReceivingImportService:
    def __init__(
        self,
        repository: TaptouchReceivingImportRepository,
        *,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._repository = repository
        self._clock = clock or (lambda: datetime.now(UTC))
        self._id_factory = id_factory or (lambda: str(uuid4()))

    def import_record(
        self,
        payload: TaptouchReceivingPayload,
        *,
        integration_principal: str,
    ) -> ReceivingImportOutcome:
        now = self._clock()
        note = ReceiveNote(
            document_number=payload.document_number,
            document_date=payload.received_at.date(),
            purchase_order_number=payload.purchase_order_number,
            currency=payload.currency,
            supplier=payload.supplier,
            location=payload.location,
            items=payload.items,
        )
        version = DocumentVersion(
            version_id=self._id_factory(),
            document_type=DocumentType.RECEIVE_NOTE,
            document_json=note.model_dump(mode="json"),
            status=DocumentVersionStatus.APPROVED,
            approved_at=now,
            created_at=now,
            source_kind=DocumentSourceKind.TAPTOUCH_RECEIVING,
            trust_method=DocumentTrustMethod.UPSTREAM_AUTHORITATIVE,
            source_system="taptouch",
            integration_principal=integration_principal,
            external_tenant_id=payload.external_tenant_id,
            external_brand_id=payload.external_brand_id,
            external_store_id=payload.external_store_id,
            external_supplier_id=payload.external_supplier_id,
            external_receiving_id=payload.external_receiving_id,
            external_version=payload.external_version,
            record_status=payload.record_status,
            upstream_updated_at=payload.upstream_updated_at,
        )
        return self._repository.import_version(version)
