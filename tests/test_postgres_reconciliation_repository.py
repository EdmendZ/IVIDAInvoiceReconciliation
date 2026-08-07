from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domain.document_sources import DocumentSourceKind, DocumentTrustMethod
from app.domain.document_versions import DocumentVersion, DocumentVersionStatus
from app.domain.documents import DocumentType
from app.domain.reconciliation import (
    LineComparison,
    MatchStatus,
    ReconciliationResult,
    ReconciliationSummary,
)
from app.domain.reconciliation_records import (
    ReconciliationPersistenceBundle,
    ReconciliationRecord,
)
from app.infra.database import Base
from app.infra.database_models import (
    AdminUserRow,
    CaseActionRow,
    CaseItemRow,
    DocumentVersionRow,
    ReconciliationCaseRow,
    ReconciliationLineResultRow,
    ReconciliationReceiveNoteRow,
    ReconciliationRow,
)
from app.infra.postgres_reconciliation_case_repository import (
    PostgresReconciliationCaseRepository,
)
from app.infra.postgres_reconciliation_repository import (
    PostgresReconciliationRepository,
)
from app.services.reconciliation_application_service import (
    ReconciliationApplicationService,
)
from app.services.reconciliation_case_factory import build_case_bundle


NOW = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)


def _record(*, requires_review: bool) -> ReconciliationRecord:
    status = MatchStatus.MISMATCH if requires_review else MatchStatus.EXACT
    line = LineComparison(
        match_key="SKU-1",
        sku="SKU-1",
        description="Item",
        invoice_quantity=Decimal("2"),
        received_quantity=Decimal("1" if requires_review else "2"),
        quantity_difference=Decimal("-1" if requires_review else "0"),
        invoice_unit_price=Decimal("10"),
        received_unit_price=Decimal("10"),
        unit_price_difference=Decimal("0"),
        invoice_amount=Decimal("20"),
        received_amount=Decimal("10" if requires_review else "20"),
        amount_difference=Decimal("-10" if requires_review else "0"),
        status=status,
    )
    return ReconciliationRecord(
        reconciliation_id="recon-abnormal" if requires_review else "recon-clean",
        invoice_version_id="invoice-version-1",
        receive_note_version_ids=["note-version-1"],
        result=ReconciliationResult(
            invoice_number="INV-1",
            receive_note_numbers=["RN-1"],
            purchase_order_match=True,
            currency_match=True,
            lines=[line],
            summary=ReconciliationSummary(
                total_lines=1,
                exact_lines=0 if requires_review else 1,
                tolerance_lines=0,
                mismatch_lines=1 if requires_review else 0,
                invoice_only_lines=0,
                receive_note_only_lines=0,
                requires_review=requires_review,
            ),
        ),
        created_by="reviewer-1",
        created_at=NOW,
    )


def _factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)


def _approved_version(
    version_id: str,
    document_type: DocumentType,
    *,
    quantity: str,
) -> DocumentVersion:
    number = "INV-1" if document_type == DocumentType.INVOICE else "RN-1"
    return DocumentVersion(
        version_id=version_id,
        task_id=f"task-{version_id}",
        source_draft_id=f"draft-{version_id}",
        version_number=1,
        document_type=document_type,
        document_json={
            "document_type": document_type.value,
            "document_number": number,
            "purchase_order_number": "PO-1",
            "items": [
                {
                    "sku": "SKU-1",
                    "description": "Item",
                    "quantity": quantity,
                    "unit_price": "10",
                    "line_total": str(Decimal(quantity) * Decimal("10")),
                }
            ],
        },
        status=DocumentVersionStatus.APPROVED,
        created_by="reviewer-1",
        approved_by="reviewer-1",
        approved_at=NOW,
        created_at=NOW,
        source_kind=(
            DocumentSourceKind.INVOICE_UPLOAD
            if document_type == DocumentType.INVOICE
            else DocumentSourceKind.EXTERNAL_RECEIVE_NOTE_UPLOAD
        ),
        trust_method=DocumentTrustMethod.HUMAN_APPROVED,
    )


class _VersionReader:
    def __init__(self, versions: list[DocumentVersion]) -> None:
        self._versions = {version.version_id: version for version in versions}

    def get_approved_version(self, version_id: str) -> DocumentVersion | None:
        return self._versions.get(version_id)

    def list_versions(self, *, status=None) -> list[DocumentVersion]:
        return [
            version
            for version in self._versions.values()
            if status is None or version.status == status
        ]

    def list_reconciliation_versions(self) -> list[DocumentVersion]:
        return list(self._versions.values())


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


@pytest.mark.parametrize("requires_review", [False, True])
def test_compare_persists_reconciliation_and_optional_case_atomically(
    requires_review: bool,
) -> None:
    factory = _factory()
    repository = PostgresReconciliationRepository(factory)
    invoice = _approved_version(
        "invoice-version-1",
        DocumentType.INVOICE,
        quantity="2",
    )
    note = _approved_version(
        "note-version-1",
        DocumentType.RECEIVE_NOTE,
        quantity="1" if requires_review else "2",
    )
    service = ReconciliationApplicationService(
        review_repository=_VersionReader([invoice, note]),
        reconciliation_repository=repository,
    )

    record = service.compare(
        invoice.version_id,
        [note.version_id],
        created_by="reviewer-1",
    )

    assert repository.get(record.reconciliation_id) == record
    stored_case = PostgresReconciliationCaseRepository(
        factory
    ).get_by_reconciliation(record.reconciliation_id)
    assert (stored_case is not None) is requires_review
    with factory() as session:
        line_rows = session.query(ReconciliationLineResultRow).all()
        assert len(line_rows) == 1
        if stored_case is not None:
            assert stored_case.items[0].line_result_id == line_rows[0].line_result_id


def test_case_item_failure_rolls_back_reconciliation_creation() -> None:
    factory = _factory()
    record = _record(requires_review=True)
    case = build_case_bundle(record, ["line-result-1"], now=NOW)
    assert case is not None
    invalid_case = case.model_copy(
        update={"items": [case.items[0], case.items[0].model_copy()]}
    )

    with pytest.raises(IntegrityError):
        PostgresReconciliationRepository(factory).create(
            ReconciliationPersistenceBundle(
                record=record,
                line_result_ids=["line-result-1"],
                case=invalid_case,
            )
        )

    with factory() as session:
        assert session.get(ReconciliationRow, record.reconciliation_id) is None
        assert session.get(ReconciliationCaseRow, case.case.case_id) is None
        assert session.query(CaseItemRow).count() == 0
        assert session.query(CaseActionRow).count() == 0


def test_atomic_create_inserts_parent_rows_before_foreign_key_children() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    # These rows represent data that predates the reconciliation transaction.
    # Enable SQLite FK enforcement only for the repository operation under test.
    with engine.begin() as connection:
        connection.execute(
            AdminUserRow.__table__.insert(),
            {
                "user_id": "reviewer-1",
                "username": "reviewer-1",
                "password_hash": "synthetic",
                "role": "reviewer",
                "is_active": True,
                "created_at": NOW,
            },
        )
        connection.execute(
            DocumentVersionRow.__table__.insert(),
            [
                {
                    "version_id": version_id,
                    "task_id": f"task-{version_id}",
                    "source_draft_id": f"draft-{version_id}",
                    "version_number": 1,
                    "document_type": document_type,
                    "document_json": {},
                    "status": "approved",
                    "created_by": "reviewer-1",
                    "approved_by": "reviewer-1",
                    "approved_at": NOW,
                    "created_at": NOW,
                    "source_kind": (
                        "invoice_upload"
                        if document_type == "invoice"
                        else "external_receive_note_upload"
                    ),
                    "trust_method": "human_approved",
                }
                for version_id, document_type in [
                    ("invoice-version-1", "invoice"),
                    ("note-version-1", "receive_note"),
                ]
            ],
        )
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1

    record = _record(requires_review=True)
    case = build_case_bundle(record, ["line-result-1"], now=NOW)
    assert case is not None
    repository = PostgresReconciliationRepository(
        sessionmaker(engine, expire_on_commit=False)
    )

    assert repository.create(
        ReconciliationPersistenceBundle(
            record=record,
            line_result_ids=["line-result-1"],
            case=case,
        )
    ) == record
