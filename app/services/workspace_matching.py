"""Deterministic workspace association rules over repository-filtered snapshots."""
from __future__ import annotations

import unicodedata

from app.domain.documents import DocumentType, LineItem, Party
from app.domain.validation import IssueSeverity
from app.domain.workspace import Candidate, MatchProposal, RevisionView


def normalize_identity(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKC", value).casefold() if c.isalnum())


def _supplier_status(left: Party | None, right: Party | None) -> str:
    if left is None or right is None:
        return "unverified"
    a = normalize_identity(left.business_number or "")
    b = normalize_identity(right.business_number or "")
    if not (a and b):
        a, b = normalize_identity(left.name), normalize_identity(right.name)
    if not (a and b):
        return "unverified"
    return "equal" if a == b else "conflict"


_UNIT_GROUPS = (
    ("kg", "kgs", "kilogram", "kilograms"), ("g", "gram", "grams"),
    ("l", "litre", "litres", "liter", "liters"), ("ml", "millilitre", "millilitres"),
    ("each", "ea", "pc", "pcs", "piece", "pieces"), ("carton", "cartons", "ctn"),
    ("case", "cases"), ("bag", "bags"),
)
_UNITS = {alias: group[0] for group in _UNIT_GROUPS for alias in group}


def _unit(value: str | None) -> str:
    value = (value or "").strip().casefold()
    return _UNITS.get(value, value)


def _item_key(item: LineItem) -> str:
    use_sku = bool(item.sku and item.sku.strip())
    normalized = normalize_identity(item.sku if use_sku else item.description)
    return ("sku:" if use_sku else "description:") + normalized if normalized else ""


def _items(revision: RevisionView) -> set[tuple[str, str]]:
    return {(_item_key(item), _unit(item.unit)) for item in revision.payload.items
            if _item_key(item) and _unit(item.unit)}


def select_candidates(invoice: RevisionView, receivings: list[RevisionView],
                      used_ids: set[str]) -> MatchProposal:
    """Scope, ready and non-voided filtering belongs to the repository."""
    inv = invoice.payload
    inv_items = _items(invoice)
    inv_po = normalize_identity(inv.purchase_order_number or "")
    supplier_unverified = _supplier_status(inv.supplier, inv.supplier) != "equal" or any(
        issue.severity == IssueSeverity.BLOCKING and issue.field_path.startswith("supplier")
        for issue in invoice.validation_issues
    )
    candidates = []
    same_subject = False
    for revision in sorted(receivings, key=lambda r: r.document_id):
        rn = revision.payload
        if rn.document_type != DocumentType.RECEIVE_NOTE:
            continue
        reasons = []
        score = 0
        supplier = "unverified" if supplier_unverified else _supplier_status(inv.supplier, rn.supplier)
        reasons.append({"equal": "SUPPLIER_MATCH", "conflict": "SUPPLIER_CONFLICT",
                        "unverified": "SUPPLIER_UNVERIFIED"}[supplier])
        currency_equal = inv.currency == rn.currency
        reasons.append("CURRENCY_MATCH" if currency_equal else "CURRENCY_CONFLICT")
        same_subject |= supplier == "equal" and currency_equal
        score += (20 if supplier == "equal" else 0) + (10 if currency_equal else 0)
        rn_po = normalize_identity(rn.purchase_order_number or "")
        po_conflict = bool(inv_po and rn_po and inv_po != rn_po)
        if inv_po and rn_po:
            reasons.append("PO_CONFLICT" if po_conflict else "PO_MATCH")
            score += 0 if po_conflict else 40
        days = abs((inv.document_date - rn.document_date).days) if inv.document_date and rn.document_date else None
        reasons.append("DATE_MISSING" if days is None else "DATE_OUTSIDE_WINDOW" if days > 30 else "DATE_NEAR")
        score += 10 if days is not None and days <= 7 else 5 if days is not None and days <= 30 else 0
        overlap = inv_items & _items(revision)
        reasons.append("ITEM_OVERLAP" if overlap else "NO_ITEM_OVERLAP")
        score += len(overlap) * 20 // len(inv_items) if inv_items else 0
        used = revision.document_id in used_ids
        if used:
            reasons.append("RECEIVING_IN_USE")
        candidates.append(Candidate(
            document_id=revision.document_id, revision_id=revision.revision_id,
            document_number=rn.document_number, score=min(score, 100),
            eligible=(supplier == "equal" and currency_equal and not used and not po_conflict
                      and days is not None and days <= 30 and bool(overlap)),
            reason_codes=reasons, source_kind="taptouch" if revision.origin == "upstream" else "upload",
            supplier_name=rn.supplier.name if rn.supplier else None,
            document_date=rn.document_date, already_used=used,
        ))
    candidates.sort(key=lambda c: (-c.score, c.document_id))
    eligible = [c for c in candidates if c.eligible]
    po_group = [c for c in eligible if "PO_MATCH" in c.reason_codes]
    selected = []
    if po_group:
        if len(po_group) <= 100:
            selected = [c.document_id for c in po_group]
    elif eligible and eligible[0].score >= 60:
        if len(eligible) == 1 or eligible[0].score - eligible[1].score >= 20:
            selected = [eligible[0].document_id]
    status = "selected" if selected else "needs_selection" if same_subject or supplier_unverified else "waiting_counterpart"
    return MatchProposal(status=status, candidates=candidates, selected_document_ids=sorted(selected))
