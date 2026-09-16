"""Pure quantity/price/amount comparison; never confirms or claims documents."""
from __future__ import annotations

from decimal import Decimal

from app.domain.validation import IssueSeverity
from app.domain.workspace import (LineResult, MetricComparison, PreviewResult,
                                  PreviewSummary, RevisionView, SubjectComparison)
from app.services.validation_service import ValidationService
from app.services.workspace_matching import _item_key, _supplier_status, _unit, normalize_identity


def _metric(left, right, tolerance, reason=None):
    difference = left - right if left is not None and right is not None else None
    status = ("unverified" if difference is None else "equal" if difference == 0
              else "within_tolerance" if abs(difference) <= tolerance else "different")
    return MetricComparison(invoice_value=left, received_value=right, difference=difference,
                            status=status, reason_code=reason)


def _aggregate(entries):
    if not entries:
        return None, None, None, False
    items = [entry[2] for entry in entries]
    quantity = sum((item.quantity for item in items), Decimal("0"))
    prices = {item.unit_price for item in items if item.unit_price is not None}
    multiple = len(prices) > 1
    price = next(iter(prices)) if len(prices) == 1 and all(item.unit_price is not None for item in items) else None
    amounts = [item.line_total if item.line_total is not None else
               item.quantity * item.unit_price if item.unit_price is not None else None for item in items]
    amount = sum(amounts, Decimal("0")) if all(value is not None for value in amounts) else None
    return quantity, price, amount, multiple


def compare_workspace(invoice: RevisionView, receivings: list[RevisionView]) -> PreviewResult:
    """Compare selected revisions. Claims and cross-record duplicates are repository checks."""
    inv = invoice.payload
    blocking = set()
    supplier_states = [_supplier_status(inv.supplier, r.payload.supplier) for r in receivings]
    supplier_states.append(_supplier_status(inv.supplier, inv.supplier))
    supplier = "conflict" if "conflict" in supplier_states else "unverified" if "unverified" in supplier_states else "equal"
    if supplier != "equal":
        blocking.add("SUPPLIER_CONFLICT" if supplier == "conflict" else "SUPPLIER_UNVERIFIED")
    currency = "equal" if all(inv.currency == r.payload.currency for r in receivings) else "conflict"
    if currency == "conflict":
        blocking.add("CURRENCY_CONFLICT")
    revisions = [invoice, *sorted(receivings, key=lambda r: r.document_id)]
    if any(r.payload.currency != "AUD" for r in revisions):
        blocking.add("UNSUPPORTED_CURRENCY")
    validator = ValidationService()
    if not normalize_identity(inv.document_number) or any(
        issue.severity == IssueSeverity.BLOCKING for r in revisions
        for issue in [*r.validation_issues, *validator.validate(r.payload).issues]
    ):
        blocking.add("VALIDATION_BLOCKED")
    groups = [{}, {}]
    units = [{}, {}]
    for side, documents in enumerate(([invoice], revisions[1:])):
        for revision in documents:
            for index, item in enumerate(revision.payload.items):
                key, unit = _item_key(item), _unit(item.unit)
                if not key:
                    blocking.add("EMPTY_ITEM_KEY")
                if not unit:
                    blocking.add("UNIT_UNVERIFIED")
                groups[side].setdefault((key, unit), []).append((revision.document_id, index, item))
                units[side].setdefault(key, set()).add(unit)
    conflicting = {key for key in units[0].keys() & units[1].keys()
                   if units[0][key] != units[1][key]}
    if conflicting:
        blocking.add("UNIT_CONFLICT")
    lines = []
    for key, unit in sorted(groups[0].keys() | groups[1].keys()):
        left, right = groups[0].get((key, unit), []), groups[1].get((key, unit), [])
        lq, lp, la, lm = _aggregate(left)
        rq, rp, ra, rm = _aggregate(right)
        reasons = []
        if not key:
            reasons.append("EMPTY_ITEM_KEY")
        if not unit:
            reasons.append("UNIT_UNVERIFIED")
        if key in conflicting:
            reasons.append("UNIT_CONFLICT")
        if lm or rm:
            reasons.append("MULTIPLE_PRICES")
        quantity = _metric(lq, rq, Decimal("0"))
        price = _metric(lp, rp, Decimal("0.01"), "MULTIPLE_PRICES" if lm or rm else None)
        amount = _metric(la, ra, Decimal("0.02"))
        statuses = {quantity.status, price.status, amount.status}
        status = ("receive_only" if not left else "invoice_only" if not right else
                  next(s for s in ("different", "unverified", "within_tolerance", "equal") if s in statuses))
        item = (left or right)[0][2]
        lines.append(LineResult(
            match_key=key, sku=item.sku, description=item.description,
            invoice_unit=unit or None if left else None, received_unit=unit or None if right else None,
            quantity=quantity, price=price, amount=amount, status=status, reason_codes=reasons,
            invoice_line_indexes=[entry[1] for entry in left],
            receive_lines=[{"document_id": entry[0], "line_index": entry[1]} for entry in right],
        ))
    aligned = [line for line in lines if line.invoice_line_indexes and line.receive_lines]
    price_verified = bool(aligned) and all(line.price.status != "unverified" for line in aligned)
    amount_verified = bool(aligned) and all(line.amount.status != "unverified" for line in aligned)
    coverage = ("full" if price_verified and amount_verified else "quantity_and_price" if price_verified
                else "quantity_and_amount" if amount_verified else "quantity_only")
    different = sum(line.status in {"different", "invoice_only", "receive_only"} for line in lines)
    unverified = sum(line.price.status == "unverified" or line.amount.status == "unverified" for line in lines)
    dimensions = ["document_total", "tax"]
    for dimension in ("price", "amount"):
        if not aligned or any(getattr(line, dimension).status == "unverified" for line in lines):
            dimensions.append(dimension)
    return PreviewResult(
        outcome="blocked" if blocking else "difference" if different or not aligned else "consistent",
        coverage=coverage, blocking_codes=sorted(blocking), unverified_dimensions=dimensions,
        lines=lines, summary=PreviewSummary(total_lines=len(lines), different_lines=different, unverified_lines=unverified),
        subject=SubjectComparison(supplier=supplier, currency=currency),
    )
