from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
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


@dataclass(frozen=True)
class SourceSupportError:
    field_path: str
    code: str
    expected: str


def _normalized(value: object) -> str:
    return re.sub(r"\s+", " ", str(value).strip()).casefold()


def validate_document_source_support(
    source_text: str,
    gold: dict,
) -> list[SourceSupportError]:
    """Check that critical non-null Gold values are visibly printed in the PDF."""

    source = _normalized(source_text)
    errors: list[SourceSupportError] = []

    def require(field_path: str, value: object | None) -> None:
        if value is None:
            return
        expected = _normalized(value)
        if expected not in source:
            errors.append(
                SourceSupportError(
                    field_path=field_path,
                    code="GOLD_VALUE_NOT_IN_SOURCE",
                    expected=str(value),
                )
            )

    require("document_number", gold.get("document_number"))
    require("purchase_order_number", gold.get("purchase_order_number"))
    require("currency", gold.get("currency"))
    require("supplier.name", gold.get("supplier", {}).get("name"))
    for index, item in enumerate(gold.get("items", [])):
        sku = item.get("sku")
        line_number = item.get("line_number")
        require(f"items.{index}.sku", sku)
        if line_number is not None and sku is not None:
            require(f"items.{index}.line_number", f"{line_number} {sku}")

    return errors


def validate() -> None:
    manifest = json.loads((DATASET_ROOT / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["synthetic"] is True
    assert manifest["case_count"] == len(EXPECTED)

    pdf_count = 0
    source_support_errors: list[str] = []
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
            gold_path = DATASET_ROOT / "gold" / case_id / f"{pdf_path.stem}.json"
            gold = json.loads(gold_path.read_text(encoding="utf-8"))
            for error in validate_document_source_support(text, gold):
                source_support_errors.append(
                    f"{relative_path}: {error.field_path} "
                    f"{error.code} expected={error.expected!r}"
                )
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

    assert not source_support_errors, "\n".join(source_support_errors)
    assert pdf_count == 17
    print(f"Validated {len(EXPECTED)} cases and {pdf_count} PDF documents")


if __name__ == "__main__":
    validate()
