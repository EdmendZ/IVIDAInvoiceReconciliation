from datetime import UTC, datetime

from app.api.dependencies import get_reconciliation_application_service
from app.domain.reconciliation import ReconciliationResult
from app.domain.reconciliation_records import ReconciliationRecord
from app.main import app
from app.services.reconciliation_export_service import render_reconciliation_csv
from tests.auth_helpers import reviewer_client


def _record() -> ReconciliationRecord:
    return ReconciliationRecord(
        reconciliation_id="recon-1",
        invoice_version_id="invoice-version-1",
        receive_note_version_ids=["note-version-1"],
        result=ReconciliationResult.model_validate(
            {
                "invoice_number": "INV/1001",
                "receive_note_numbers": ["RN-1"],
                "purchase_order_match": True,
                "currency_match": True,
                "lines": [
                    {
                        "match_key": "sku:CHEESE",
                        "sku": "CHEESE",
                        "description": "Mozzarella, 2kg",
                        "invoice_quantity": "2",
                        "received_quantity": "1",
                        "quantity_difference": "-1",
                        "invoice_unit_price": "10.00",
                        "received_unit_price": "10.00",
                        "unit_price_difference": "0.00",
                        "invoice_amount": "20.00",
                        "received_amount": "10.00",
                        "amount_difference": "-10.00",
                        "status": "mismatch",
                        "reasons": ["Quantity differs"],
                    }
                ],
                "summary": {
                    "total_lines": 1,
                    "exact_lines": 0,
                    "tolerance_lines": 0,
                    "mismatch_lines": 1,
                    "invoice_only_lines": 0,
                    "receive_note_only_lines": 0,
                    "requires_review": True,
                },
            }
        ),
        created_by="reviewer-1",
        created_at=datetime(2026, 8, 1, 8, 30, tzinfo=UTC),
    )


class RecordService:
    def __init__(self, record: ReconciliationRecord | None) -> None:
        self.record = record

    def get_record(self, reconciliation_id: str) -> ReconciliationRecord:
        from app.services.reconciliation_application_service import (
            ReconciliationNotFound,
        )

        if self.record is None or self.record.reconciliation_id != reconciliation_id:
            raise ReconciliationNotFound("Reconciliation not found")
        return self.record


def test_csv_preserves_metadata_and_quotes_comma_fields() -> None:
    content = render_reconciliation_csv(_record()).decode("utf-8-sig")

    assert content.startswith("Reconciliation ID,recon-1\r\n")
    assert 'CHEESE,"Mozzarella, 2kg",2,1,-1' in content
    assert "Requires review,Yes" in content


def test_csv_escapes_user_controlled_excel_formulas() -> None:
    record = _record()
    record.result.lines[0].description = "=HYPERLINK(\"https://example.test\")"

    content = render_reconciliation_csv(record).decode("utf-8-sig")

    assert "'=HYPERLINK" in content


def test_csv_export_sets_download_name() -> None:
    previous = app.dependency_overrides.get(get_reconciliation_application_service)
    app.dependency_overrides[get_reconciliation_application_service] = lambda: RecordService(
        _record()
    )
    try:
        with reviewer_client(app) as client:
            response = client.get("/api/reconciliations/recon-1/export.csv")
    finally:
        if previous is None:
            app.dependency_overrides.pop(
                get_reconciliation_application_service,
                None,
            )
        else:
            app.dependency_overrides[get_reconciliation_application_service] = previous

    assert response.status_code == 200
    assert response.content.startswith(b"\xef\xbb\xbf")
    assert response.headers["content-disposition"] == (
        'attachment; filename="reconciliation-INV-1001.csv"'
    )


def test_csv_export_returns_404_for_unknown_record() -> None:
    previous = app.dependency_overrides.get(get_reconciliation_application_service)
    app.dependency_overrides[get_reconciliation_application_service] = lambda: RecordService(
        None
    )
    try:
        with reviewer_client(app) as client:
            response = client.get("/api/reconciliations/missing/export.csv")
    finally:
        if previous is None:
            app.dependency_overrides.pop(
                get_reconciliation_application_service,
                None,
            )
        else:
            app.dependency_overrides[get_reconciliation_application_service] = previous

    assert response.status_code == 404
