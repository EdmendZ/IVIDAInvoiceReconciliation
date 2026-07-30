from __future__ import annotations

import re
from datetime import date

from app.domain.documents import Invoice, LineItem, ReceiveNote
from app.domain.reconciliation_candidates import (
    CandidateSignal,
    ReconciliationCandidate,
)


def _normalized_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _item_key(item: LineItem) -> str:
    if item.sku and item.sku.strip():
        return f"sku:{_normalized_text(item.sku)}"
    return f"description:{_normalized_text(item.description)}"


def _party_name(document: Invoice | ReceiveNote, field: str) -> str | None:
    party = getattr(document, field)
    return party.name if party else None


def _add_identity_signal(
    signals: list[CandidateSignal],
    *,
    code: str,
    label: str,
    left: str | None,
    right: str | None,
    match_weight: int,
    conflict_weight: int,
) -> int:
    if not left or not right:
        signals.append(
            CandidateSignal(
                code=f"{code}_missing",
                outcome="unknown",
                message=f"{label} is missing on one or both documents",
                weight=0,
            )
        )
        return 0
    if _normalized_text(left) == _normalized_text(right):
        signals.append(
            CandidateSignal(
                code=f"{code}_match",
                outcome="match",
                message=f"{label} matches: {left}",
                weight=match_weight,
            )
        )
        return match_weight
    signals.append(
        CandidateSignal(
            code=f"{code}_mismatch",
            outcome="conflict",
            message=f"{label} differs: {left} / {right}",
            weight=conflict_weight,
        )
    )
    return conflict_weight


def _date_signal(
    invoice_date: date | None,
    note_date: date | None,
) -> tuple[int, CandidateSignal]:
    if invoice_date is None or note_date is None:
        return 0, CandidateSignal(
            code="date_missing",
            outcome="unknown",
            message="Document date is missing on one or both documents",
            weight=0,
        )
    days = abs((invoice_date - note_date).days)
    if days <= 7:
        weight = 10
    elif days <= 30:
        weight = 5
    elif days <= 60:
        weight = 0
    else:
        weight = -5
    return weight, CandidateSignal(
        code="date_proximity",
        outcome="match" if days <= 30 else "conflict",
        message=f"Document dates are {days} day(s) apart",
        weight=weight,
    )


def assess_candidate(
    *,
    invoice: Invoice,
    receive_note: ReceiveNote,
    receive_note_version_id: str,
) -> ReconciliationCandidate:
    signals: list[CandidateSignal] = []
    score = 0
    same_document_number = (
        _normalized_text(invoice.document_number)
        == _normalized_text(receive_note.document_number)
    )
    if same_document_number:
        score -= 100
        signals.append(
            CandidateSignal(
                code="same_document_number",
                outcome="conflict",
                message=(
                    "Invoice and Receive Note have the same document number; "
                    "verify that the document type was classified correctly"
                ),
                weight=-100,
            )
        )
    score += _add_identity_signal(
        signals,
        code="purchase_order",
        label="Purchase order",
        left=invoice.purchase_order_number,
        right=receive_note.purchase_order_number,
        match_weight=40,
        conflict_weight=-40,
    )
    score += _add_identity_signal(
        signals,
        code="supplier",
        label="Supplier",
        left=_party_name(invoice, "supplier"),
        right=_party_name(receive_note, "supplier"),
        match_weight=20,
        conflict_weight=-15,
    )
    score += _add_identity_signal(
        signals,
        code="location",
        label="Location",
        left=_party_name(invoice, "location"),
        right=_party_name(receive_note, "location"),
        match_weight=10,
        conflict_weight=-5,
    )

    if invoice.currency == receive_note.currency:
        score += 10
        signals.append(
            CandidateSignal(
                code="currency_match",
                outcome="match",
                message=f"Currency matches: {invoice.currency}",
                weight=10,
            )
        )
    else:
        score -= 25
        signals.append(
            CandidateSignal(
                code="currency_mismatch",
                outcome="conflict",
                message=(
                    f"Currency differs: {invoice.currency} / "
                    f"{receive_note.currency}"
                ),
                weight=-25,
            )
        )

    date_weight, date_signal = _date_signal(
        invoice.document_date,
        receive_note.document_date,
    )
    score += date_weight
    signals.append(date_signal)

    invoice_items = {_item_key(item) for item in invoice.items}
    note_items = {_item_key(item) for item in receive_note.items}
    overlap_count = len(invoice_items & note_items)
    overlap_ratio = overlap_count / len(invoice_items) if invoice_items else 0
    item_weight = round(overlap_ratio * 20)
    if overlap_count:
        score += item_weight
        signals.append(
            CandidateSignal(
                code="item_overlap",
                outcome="match",
                message=(
                    f"{overlap_count} item(s) overlap "
                    f"({overlap_ratio:.0%} of invoice items)"
                ),
                weight=item_weight,
            )
        )
    else:
        score -= 20
        signals.append(
            CandidateSignal(
                code="no_item_overlap",
                outcome="conflict",
                message="No invoice items overlap with this receive note",
                weight=-20,
            )
        )

    bounded_score = max(0, min(100, score))
    blocking_codes = {
        "same_document_number",
        "purchase_order_mismatch",
        "currency_mismatch",
        "no_item_overlap",
    }
    has_blocking_conflict = any(
        signal.code in blocking_codes for signal in signals
    )
    confidence = (
        "high"
        if bounded_score >= 75
        else "medium"
        if bounded_score >= 45
        else "low"
    )
    return ReconciliationCandidate(
        receive_note_version_id=receive_note_version_id,
        document_number=receive_note.document_number,
        purchase_order_number=receive_note.purchase_order_number,
        supplier_name=(
            receive_note.supplier.name if receive_note.supplier else None
        ),
        document_date=(
            receive_note.document_date.isoformat()
            if receive_note.document_date
            else None
        ),
        score=bounded_score,
        confidence=confidence,
        recommended=bounded_score >= 60 and not has_blocking_conflict,
        signals=signals,
    )
