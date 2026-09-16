from app.domain.documents import Invoice
from app.domain.validation import IssueSeverity
from app.services.validation_service import ValidationService


def _invoice(**updates) -> Invoice:
    payload = {
        "document_type": "invoice",
        "document_number": "INV-1",
        "purchase_order_number": "PO-1",
        "subtotal": "100.00",
        "tax_total": "10.00",
        "total": "110.00",
        "items": [
            {
                "description": "Taxable cheese",
                "quantity": "2",
                "unit_price": "45.00",
                "line_total": "90.00",
                "tax_code": "GST",
                "tax_amount": "10.00",
            },
            {
                "description": "GST-free item",
                "quantity": "1",
                "unit_price": "10.00",
                "line_total": "10.00",
                "tax_code": "GST_FREE",
                "tax_amount": "0.00",
            },
        ],
    }
    payload.update(updates)
    return Invoice.model_validate(payload)


def test_taxable_and_gst_free_lines_validate_separately() -> None:
    report = ValidationService().validate(_invoice())
    assert report.blocking_count == 0


def test_wrong_total_is_blocking() -> None:
    report = ValidationService().validate(_invoice(total="120.00"))
    issue = next(
        item for item in report.issues if item.rule_code == "TOTAL_MISMATCH"
    )
    assert issue.severity == IssueSeverity.BLOCKING


def test_missing_po_is_warning() -> None:
    report = ValidationService().validate(
        _invoice(purchase_order_number=None)
    )
    assert report.has_warning("PO_MISSING")


def test_partial_tax_amounts_do_not_treat_missing_as_zero() -> None:
    invoice = _invoice()
    invoice.items[1].tax_amount = None
    invoice.tax_total = 12
    invoice.total = 112
    assert not any(issue.rule_code == "TAX_TOTAL_MISMATCH" for issue in ValidationService().validate(invoice).issues)


def test_all_known_tax_amounts_still_detect_mismatch() -> None:
    report = ValidationService().validate(_invoice(tax_total="12", total="112"))
    assert any(issue.rule_code == "TAX_TOTAL_MISMATCH" and issue.severity == IssueSeverity.BLOCKING for issue in report.issues)
