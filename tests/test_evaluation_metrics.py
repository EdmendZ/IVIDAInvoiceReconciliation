from decimal import Decimal

from app.evaluation.field_metrics import compare_documents


def test_metrics_match_decimal_strings_and_lines_by_sku() -> None:
    gold = {
        "document_number": "INV-1",
        "total": "378.84",
        "items": [
            {
                "sku": "FLOUR-12.5",
                "description": "Pizza flour",
                "quantity": "8",
            }
        ],
    }
    predicted = {
        "document_number": "inv-1",
        "total": "378.840",
        "items": [
            {
                "sku": "flour-12.5",
                "description": "Pizza  flour",
                "quantity": 8,
            }
        ],
    }

    result = compare_documents(predicted, gold)

    assert result.correct == result.total
    assert result.field_accuracy == Decimal("1")
    assert result.line_item_f1 == Decimal("1")


def test_metrics_report_missing_and_hallucinated_lines() -> None:
    gold = {
        "items": [
            {"sku": "A", "description": "A", "quantity": "1"},
            {"sku": "B", "description": "B", "quantity": "1"},
        ]
    }
    predicted = {
        "items": [
            {"sku": "A", "description": "A", "quantity": "1"},
            {"sku": "C", "description": "C", "quantity": "1"},
        ]
    }

    result = compare_documents(predicted, gold)

    assert result.matched_lines == 1
    assert result.missing_lines == 1
    assert result.extra_lines == 1
    assert result.line_item_f1 == Decimal("0.5")


def test_evidence_indices_map_to_canonical_line_keys() -> None:
    document = {
        "document_number": "INV-1",
        "items": [
            {
                "sku": "A",
                "description": "Cheese",
                "quantity": "1",
            }
        ],
    }

    result = compare_documents(
        document,
        document,
        {
            "document.document_number",
            "document.items[0].sku",
            "document.items[0].description",
            "document.items[0].quantity",
        },
    )

    assert result.evidence_covered == result.evidence_total
    assert result.evidence_coverage == Decimal("1")
