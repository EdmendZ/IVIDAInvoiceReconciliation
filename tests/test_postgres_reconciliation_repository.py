from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.infra.database import Base
from app.infra.database_models import (
    ReconciliationReceiveNoteRow,
    ReconciliationRow,
)
from app.infra.postgres_reconciliation_repository import (
    PostgresReconciliationRepository,
)


def test_get_rehydrates_persisted_result_snapshot() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[
            ReconciliationRow.__table__,
            ReconciliationReceiveNoteRow.__table__,
        ],
    )
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as session:
        session.add(
            ReconciliationRow(
                reconciliation_id="recon-1",
                invoice_version_id="invoice-version-1",
                result_json={
                    "invoice_number": "INV-1",
                    "receive_note_numbers": ["RN-1"],
                    "purchase_order_match": True,
                    "currency_match": True,
                    "lines": [],
                    "summary": {
                        "total_lines": 0,
                        "exact_lines": 0,
                        "tolerance_lines": 0,
                        "mismatch_lines": 0,
                        "invoice_only_lines": 0,
                        "receive_note_only_lines": 0,
                        "requires_review": False,
                    },
                },
                created_by="reviewer-1",
                created_at=datetime(2026, 8, 1, tzinfo=UTC),
            )
        )
        session.add(
            ReconciliationReceiveNoteRow(
                reconciliation_id="recon-1",
                receive_note_version_id="note-version-1",
            )
        )
        session.commit()

    record = PostgresReconciliationRepository(factory).get("recon-1")

    assert record is not None
    assert record.result.invoice_number == "INV-1"
    assert record.receive_note_version_ids == ["note-version-1"]
    assert PostgresReconciliationRepository(factory).get("missing") is None
