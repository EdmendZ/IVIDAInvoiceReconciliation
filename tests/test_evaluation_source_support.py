from pypdf import PdfReader

from tools.generate_evaluation_dataset import CASES, document_json, render_pdf
from tools.validate_evaluation_dataset import validate_document_source_support


def test_generated_invoice_prints_supplier_name_and_line_numbers(tmp_path) -> None:
    document = CASES[0].invoice
    pdf_path = tmp_path / "invoice.pdf"

    render_pdf(document, pdf_path)

    text = PdfReader(pdf_path).pages[0].extract_text()
    gold = document_json(document)
    assert gold["supplier"]["name"] in text
    assert "Line" in text
    for item in gold["items"]:
        assert f"{item['line_number']} {item['sku']}" in " ".join(text.split())


def test_source_support_validator_reports_missing_supplier() -> None:
    gold = {
        "document_number": "INV-1",
        "purchase_order_number": "PO-1",
        "currency": "AUD",
        "supplier": {"name": "Southern Cross Foodservice Pty Ltd"},
        "items": [],
    }

    errors = validate_document_source_support(
        "TAX INVOICE INV-1 Purchase Order PO-1 Currency AUD",
        gold,
    )

    assert [(item.field_path, item.code) for item in errors] == [
        ("supplier.name", "GOLD_VALUE_NOT_IN_SOURCE")
    ]


def test_source_support_validator_accepts_printed_critical_values(tmp_path) -> None:
    document = CASES[0].invoice
    pdf_path = tmp_path / "invoice.pdf"
    render_pdf(document, pdf_path)
    source_text = PdfReader(pdf_path).pages[0].extract_text()

    errors = validate_document_source_support(source_text, document_json(document))

    assert errors == []
