from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from app.domain.documents import LineItem
from app.domain.reconciliation import (
    LineComparison,
    MatchStatus,
    ReconciliationRequest,
    ReconciliationResult,
    ReconciliationSummary,
)


@dataclass
class _AggregatedLine:
    sku: str | None
    description: str
    quantity: Decimal = Decimal("0")
    amount: Decimal | None = None
    weighted_unit_price: Decimal | None = None


def _normalized_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _match_key(item: LineItem) -> str:
    if item.sku and item.sku.strip():
        return f"sku:{_normalized_text(item.sku)}"
    return f"description:{_normalized_text(item.description)}"


def _item_amount(item: LineItem) -> Decimal | None:
    if item.line_total is not None:
        return item.line_total
    if item.unit_price is not None:
        return item.quantity * item.unit_price
    return None


def _aggregate(items: list[LineItem]) -> dict[str, _AggregatedLine]:
    grouped: dict[str, list[LineItem]] = defaultdict(list)
    for item in items:
        grouped[_match_key(item)].append(item)

    result: dict[str, _AggregatedLine] = {}
    for key, matching_items in grouped.items():
        quantity = sum((item.quantity for item in matching_items), Decimal("0"))
        amounts = [_item_amount(item) for item in matching_items]
        amount = None if any(value is None for value in amounts) else sum(amounts, Decimal("0"))
        price_extensions = [
            item.quantity * item.unit_price
            for item in matching_items
            if item.unit_price is not None
        ]
        weighted_price = (
            sum(price_extensions, Decimal("0")) / quantity
            if len(price_extensions) == len(matching_items) and quantity
            else None
        )
        first = matching_items[0]
        result[key] = _AggregatedLine(
            sku=first.sku,
            description=first.description,
            quantity=quantity,
            amount=amount,
            weighted_unit_price=weighted_price,
        )
    return result


def _absolute_difference(left: Decimal | None, right: Decimal | None) -> Decimal | None:
    if left is None or right is None:
        return None
    return left - right


def _classify(
    invoice_line: _AggregatedLine | None,
    received_line: _AggregatedLine | None,
    request: ReconciliationRequest,
) -> tuple[MatchStatus, list[str]]:
    if invoice_line is None:
        return MatchStatus.RECEIVE_NOTE_ONLY, ["Item exists only on receive note"]
    if received_line is None:
        return MatchStatus.INVOICE_ONLY, ["Item exists only on invoice"]

    tolerance = request.tolerance
    differences = {
        "Quantity differs": abs(invoice_line.quantity - received_line.quantity),
        "Unit price differs": (
            abs(invoice_line.weighted_unit_price - received_line.weighted_unit_price)
            if invoice_line.weighted_unit_price is not None
            and received_line.weighted_unit_price is not None
            else Decimal("0")
        ),
        "Amount differs": (
            abs(invoice_line.amount - received_line.amount)
            if invoice_line.amount is not None and received_line.amount is not None
            else Decimal("0")
        ),
    }
    limits = {
        "Quantity differs": tolerance.quantity,
        "Unit price differs": tolerance.unit_price,
        "Amount differs": tolerance.amount,
    }
    reasons = [label for label, difference in differences.items() if difference > limits[label]]
    if reasons:
        return MatchStatus.MISMATCH, reasons
    if any(difference > 0 for difference in differences.values()):
        return MatchStatus.WITHIN_TOLERANCE, []
    return MatchStatus.EXACT, []


def reconcile(request: ReconciliationRequest) -> ReconciliationResult:
    invoice_lines = _aggregate(request.invoice.items)
    received_items = [item for note in request.receive_notes for item in note.items]
    received_lines = _aggregate(received_items)

    comparisons: list[LineComparison] = []
    for key in sorted(invoice_lines.keys() | received_lines.keys()):
        invoice_line = invoice_lines.get(key)
        received_line = received_lines.get(key)
        status, reasons = _classify(invoice_line, received_line, request)
        representative = invoice_line or received_line
        assert representative is not None

        invoice_quantity = invoice_line.quantity if invoice_line else Decimal("0")
        received_quantity = received_line.quantity if received_line else Decimal("0")
        invoice_price = invoice_line.weighted_unit_price if invoice_line else None
        received_price = received_line.weighted_unit_price if received_line else None
        invoice_amount = invoice_line.amount if invoice_line else None
        received_amount = received_line.amount if received_line else None

        comparisons.append(
            LineComparison(
                match_key=key,
                sku=representative.sku,
                description=representative.description,
                invoice_quantity=invoice_quantity,
                received_quantity=received_quantity,
                quantity_difference=invoice_quantity - received_quantity,
                invoice_unit_price=invoice_price,
                received_unit_price=received_price,
                unit_price_difference=_absolute_difference(invoice_price, received_price),
                invoice_amount=invoice_amount,
                received_amount=received_amount,
                amount_difference=_absolute_difference(invoice_amount, received_amount),
                status=status,
                reasons=reasons,
            )
        )

    statuses = [line.status for line in comparisons]
    review_statuses = {
        MatchStatus.MISMATCH,
        MatchStatus.INVOICE_ONLY,
        MatchStatus.RECEIVE_NOTE_ONLY,
    }
    purchase_orders = {
        note.purchase_order_number
        for note in request.receive_notes
        if note.purchase_order_number is not None
    }
    purchase_order_match = (
        None
        if request.invoice.purchase_order_number is None or not purchase_orders
        else purchase_orders == {request.invoice.purchase_order_number}
    )

    return ReconciliationResult(
        invoice_number=request.invoice.document_number,
        receive_note_numbers=[note.document_number for note in request.receive_notes],
        purchase_order_match=purchase_order_match,
        currency_match=all(
            note.currency == request.invoice.currency for note in request.receive_notes
        ),
        lines=comparisons,
        summary=ReconciliationSummary(
            total_lines=len(comparisons),
            exact_lines=statuses.count(MatchStatus.EXACT),
            tolerance_lines=statuses.count(MatchStatus.WITHIN_TOLERANCE),
            mismatch_lines=statuses.count(MatchStatus.MISMATCH),
            invoice_only_lines=statuses.count(MatchStatus.INVOICE_ONLY),
            receive_note_only_lines=statuses.count(MatchStatus.RECEIVE_NOTE_ONLY),
            requires_review=(
                any(status in review_statuses for status in statuses)
                or purchase_order_match is False
                or not all(
                    note.currency == request.invoice.currency
                    for note in request.receive_notes
                )
            ),
        ),
    )
