from __future__ import annotations

import json
import sys
from pathlib import Path

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.domain.reconciliation import ReconciliationRequest
from app.services.reconciliation_service import reconcile


DATASET_ROOT = ROOT / "evaluation_data"

EXPECTED = {
    "case-01-exact-single": {
        "exact_lines": 3,
        "mismatch_lines": 0,
        "invoice_only_lines": 0,
        "receive_note_only_lines": 0,
        "requires_review": False,
    },
    "case-02-exact-split-delivery": {
        "exact_lines": 2,
        "mismatch_lines": 0,
        "invoice_only_lines": 0,
        "receive_note_only_lines": 0,
        "requires_review": False,
    },
    "case-03-short-delivery": {
        "exact_lines": 1,
        "mismatch_lines": 1,
        "invoice_only_lines": 0,
        "receive_note_only_lines": 0,
        "requires_review": True,
    },
    "case-04-price-variance": {
        "exact_lines": 1,
        "mismatch_lines": 1,
        "invoice_only_lines": 0,
        "receive_note_only_lines": 0,
        "requires_review": True,
    },
    "case-05-invoice-only-line": {
        "exact_lines": 2,
        "mismatch_lines": 0,
        "invoice_only_lines": 1,
        "receive_note_only_lines": 0,
        "requires_review": True,
    },
    "case-06-receive-note-only-line": {
        "exact_lines": 2,
        "mismatch_lines": 0,
        "invoice_only_lines": 0,
        "receive_note_only_lines": 1,
        "requires_review": True,
    },
    "case-07-rounding-tolerance": {
        "exact_lines": 1,
        "mismatch_lines": 0,
        "invoice_only_lines": 0,
        "receive_note_only_lines": 0,
        "requires_review": False,
    },
    "case-08-po-mismatch": {
        "exact_lines": 2,
        "mismatch_lines": 0,
        "invoice_only_lines": 0,
        "receive_note_only_lines": 0,
        "requires_review": True,
    },
}


def validate() -> None:
    manifest = json.loads((DATASET_ROOT / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["synthetic"] is True
    assert manifest["case_count"] == len(EXPECTED)

    pdf_count = 0
    for case in manifest["cases"]:
        case_id = case["case_id"]
        assert case_id in EXPECTED
        for relative_path in case["documents"]:
            pdf_path = DATASET_ROOT / relative_path
            assert pdf_path.exists(), pdf_path
            reader = PdfReader(pdf_path)
            assert len(reader.pages) == 1
            text = reader.pages[0].extract_text()
            assert "SYNTHETIC EVALUATION DOCUMENT" in text
            assert "AUD" in text
            pdf_count += 1

        request_path = DATASET_ROOT / case["gold_request"]
        request = ReconciliationRequest.model_validate_json(
            request_path.read_text(encoding="utf-8")
        )
        result = reconcile(request)
        actual = result.summary.model_dump()
        for key, expected_value in EXPECTED[case_id].items():
            assert actual[key] == expected_value, (
                f"{case_id}: {key} expected {expected_value}, got {actual[key]}"
            )

        if case_id == "case-07-rounding-tolerance":
            assert result.summary.tolerance_lines == 1
        if case_id == "case-08-po-mismatch":
            assert result.purchase_order_match is False

    assert pdf_count == 17
    print(f"Validated {len(EXPECTED)} cases and {pdf_count} PDF documents")


if __name__ == "__main__":
    validate()
