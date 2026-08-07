from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.domain.document_sources import UpstreamRecordStatus
from app.domain.taptouch_receiving import TaptouchReceivingPayload
from app.infra.database import Base
from app.infra.database_models import (
    DocumentDraftRow,
    DocumentVersionRow,
    ExtractionTaskRow,
    ReviewActionRow,
)
from app.infra.postgres_taptouch_receiving_repository import (
    PostgresTaptouchReceivingRepository,
)
from app.infra.postgres_review_repository import PostgresReviewRepository
from app.services.taptouch_receiving_import_service import (
    ReceivingIdentityConflict,
    ReceivingVersionConflict,
    TaptouchReceivingImportService,
)

NOW = datetime(2026, 8, 7, 4, 30, tzinfo=UTC)


def _payload(**overrides) -> TaptouchReceivingPayload:
    data = {
        "external_tenant_id": "tenant-1",
        "external_store_id": "store-1",
        "external_supplier_id": "supplier-1",
        "external_receiving_id": "receiving-1",
        "external_version": 1,
        "record_status": "active",
        "document_number": "GRN-1001",
        "received_at": "2026-08-07T04:30:00Z",
        "currency": "aud",
        "supplier": {"name": "Fresh Foods"},
        "location": {"name": "Sydney Store"},
        "items": [
            {
                "sku": "CHEESE",
                "description": "Mozzarella",
                "quantity": "2",
                "unit_price": "10.00",
                "line_total": "20.00",
            }
        ],
        "upstream_updated_at": "2026-08-07T04:31:00Z",
    }
    data.update(overrides)
    return TaptouchReceivingPayload.model_validate(data)


def _service():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    service = TaptouchReceivingImportService(
        PostgresTaptouchReceivingRepository(factory),
        clock=lambda: NOW,
        id_factory=lambda: "version-fixed",
    )
    return service, factory


def test_valid_payload_maps_and_replays_idempotently() -> None:
    service, _ = _service()
    first = service.import_record(_payload())
    replay = service.import_record(_payload())
    assert first.created is True
    assert replay.created is False
    assert replay.version.version_id == first.version.version_id
    assert first.version.document_json["document_date"] == "2026-08-07"
    assert first.version.document_json["currency"] == "AUD"


def test_higher_voided_version_suppresses_older_active_version() -> None:
    service, factory = _service()
    service.import_record(_payload())
    service._id_factory = lambda: "version-2"
    newer = service.import_record(_payload(external_version=2, record_status="voided"))
    assert newer.version.record_status == UpstreamRecordStatus.VOIDED
    reader = PostgresReviewRepository(factory)
    assert reader.get_approved_version("version-fixed") is None
    assert reader.get_approved_version("version-2") is None
    assert reader.list_reconciliation_versions() == []
    with pytest.raises(ReceivingVersionConflict):
        service.import_record(_payload())


def test_same_version_with_changed_content_conflicts() -> None:
    service, _ = _service()
    service.import_record(_payload())
    with pytest.raises(ReceivingIdentityConflict):
        service.import_record(_payload(document_number="GRN-CHANGED"))


def test_import_creates_no_extraction_or_review_lineage() -> None:
    service, factory = _service()
    service.import_record(_payload())
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(DocumentVersionRow)) == 1
        assert session.scalar(select(func.count()).select_from(ExtractionTaskRow)) == 0
        assert session.scalar(select(func.count()).select_from(DocumentDraftRow)) == 0
        assert session.scalar(select(func.count()).select_from(ReviewActionRow)) == 0


def test_naive_timestamp_is_rejected() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        _payload(received_at="2026-08-07T14:30:00")
