from decimal import Decimal

from app.domain.reconciliation import (
    MatchStatus,
    ReconciliationRequest,
    ReconciliationTolerance,
)
from app.services.reconciliation_service import reconcile


def _request() -> ReconciliationRequest:
    return ReconciliationRequest.model_validate(
        {
            "invoice": {
                "document_number": "INV-1",
                "purchase_order_number": "PO-1",
                "items": [
                    {
                        "sku": "A-1",
                        "description": "Tomato",
                        "quantity": "10",
                        "unit_price": "2.00",
                    },
                    {
                        "sku": "B-1",
                        "description": "Cheese",
                        "quantity": "2",
                        "unit_price": "5.00",
                    },
                ],
            },
            "receive_notes": [
                {
                    "document_number": "RN-1",
                    "purchase_order_number": "PO-1",
                    "items": [
                        {
                            "sku": "A-1",
                            "description": "Tomato",
                            "quantity": "6",
                            "unit_price": "2.00",
                        }
                    ],
                },
                {
                    "document_number": "RN-2",
                    "purchase_order_number": "PO-1",
                    "items": [
                        {
                            "sku": "A-1",
                            "description": "Tomato",
                            "quantity": "4",
                            "unit_price": "2.00",
                        },
                        {
                            "sku": "C-1",
                            "description": "Olives",
                            "quantity": "1",
                            "unit_price": "3.00",
                        },
                    ],
                },
            ],
        }
    )


def test_multiple_receive_notes_are_aggregated() -> None:
    result = reconcile(_request())
    lines = {line.sku: line for line in result.lines}

    assert lines["A-1"].status == MatchStatus.EXACT
    assert lines["A-1"].received_quantity == Decimal("10")
    assert lines["B-1"].status == MatchStatus.INVOICE_ONLY
    assert lines["C-1"].status == MatchStatus.RECEIVE_NOTE_ONLY
    assert result.summary.requires_review is True


def test_small_amount_difference_can_be_tolerated() -> None:
    request = _request()
    request.receive_notes[1].items[0].unit_price = Decimal("2.001")
    request.tolerance = ReconciliationTolerance(
        quantity=Decimal("0"),
        unit_price=Decimal("0.01"),
        amount=Decimal("0.01"),
    )

    result = reconcile(request)
    tomato = next(line for line in result.lines if line.sku == "A-1")

    assert tomato.status == MatchStatus.WITHIN_TOLERANCE

