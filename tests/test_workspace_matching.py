from datetime import datetime, timezone
from uuid import UUID

import pytest

from app.domain.workspace import RevisionView
from app.services.workspace_matching import normalize_identity, select_candidates


def revision(n=1, kind="invoice", **updates):
    payload = dict(document_type=kind, document_number="SAME", document_date="2026-01-01",
                   purchase_order_number="PO-1", supplier={"name": "Acme", "business_number": "12-34"},
                   items=[dict(description="Rice", sku="R1", unit="bag", quantity="10")])
    payload.update(updates)
    return RevisionView(document_id=str(UUID(int=n)), revision_id=str(UUID(int=n+1000)), sequence=1,
                        origin="upstream" if kind == "receive_note" else "extracted", payload=payload,
                        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc))


def test_identity_nfkc_unicode_and_missing():
    assert normalize_identity(" ＡＢ-１２ 中 文! ") == "ab12中文"
    assert normalize_identity("Straße") == "strasse"
    assert normalize_identity(" ---! ") == ""
    assert normalize_identity("大米") != normalize_identity("面粉")


def test_same_po_group_all_selected_sorted_independent_of_input_order():
    inv = revision()
    notes = [revision(3, "receive_note"), revision(2, "receive_note")]
    proposal = select_candidates(inv, notes, set())
    assert proposal.status == "selected"
    assert proposal.selected_document_ids == sorted(r.document_id for r in notes)
    assert proposal == select_candidates(inv, list(reversed(notes)), set())
    assert proposal.candidates[0].score == 100
    assert proposal.candidates[0].source_kind == "taptouch"


@pytest.mark.parametrize("count,status", [(100, "selected"), (101, "needs_selection")])
def test_po_group_size_limit(count, status):
    proposal = select_candidates(revision(), [revision(n+2, "receive_note") for n in range(count)], set())
    assert proposal.status == status
    assert len(proposal.selected_document_ids) == (count if count <= 100 else 0)


def test_no_po_ambiguity_and_unique_maximum():
    inv = revision(purchase_order_number=None)
    a = revision(2, "receive_note", purchase_order_number=None)
    b = revision(3, "receive_note", purchase_order_number=None)
    assert select_candidates(inv, [a, b], set()).status == "needs_selection"
    assert select_candidates(inv, [a], set()).selected_document_ids == [a.document_id]
    assert select_candidates(inv, [], set()).status == "waiting_counterpart"


@pytest.mark.parametrize("date,score,eligible", [("2026-01-08",100,True), ("2026-01-09",95,True),
    ("2026-01-31",95,True), ("2026-02-01",90,False), (None,90,False), ("2025-12-25",100,True)])
def test_date_boundaries(date, score, eligible):
    proposal = select_candidates(revision(), [revision(2, "receive_note", document_date=date)], set())
    assert proposal.candidates[0].score == score
    assert proposal.candidates[0].eligible is eligible
    assert proposal.status == ("selected" if eligible else "needs_selection")


@pytest.mark.parametrize("updates,reason", [
    ({"supplier":{"name":"Acme", "business_number":"DIFFERENT"}}, "SUPPLIER_CONFLICT"),
    ({"supplier":None}, "SUPPLIER_UNVERIFIED"),
    ({"currency":"USD"}, "CURRENCY_CONFLICT"),
    ({"purchase_order_number":"OTHER"}, "PO_CONFLICT"),
    ({"items":[dict(description="Rice", sku="R1", unit="kg", quantity="10")]}, "NO_ITEM_OVERLAP"),
])
def test_blocked_candidates_explain_reason(updates, reason):
    proposal = select_candidates(revision(), [revision(2, "receive_note", **updates)], set())
    assert not proposal.candidates[0].eligible
    assert reason in proposal.candidates[0].reason_codes
    assert not proposal.selected_document_ids


def test_occupied_candidate_retained_and_manual_origin_maps_upload():
    rn = revision(2, "receive_note").model_copy(update={"origin":"manual"})
    candidate = select_candidates(revision(), [rn], {rn.document_id}).candidates[0]
    assert candidate.already_used and not candidate.eligible
    assert "RECEIVING_IN_USE" in candidate.reason_codes
    assert candidate.source_kind == "upload"


def test_punctuation_po_and_abn_are_missing_not_identity_matches():
    inv = revision(purchase_order_number="--", supplier={"name":"Acme", "business_number":"---"})
    rn = revision(2, "receive_note", purchase_order_number="!!", supplier={"name":"Other", "business_number":"!!"})
    candidate = select_candidates(inv, [rn], set()).candidates[0]
    assert "PO_MATCH" not in candidate.reason_codes
    assert "SUPPLIER_CONFLICT" in candidate.reason_codes
    assert not candidate.eligible


def test_supplier_missing_invoice_never_waiting_even_without_receivings():
    assert select_candidates(revision(supplier=None), [], set()).status == "needs_selection"


def test_abn_missing_on_one_side_uses_exact_name():
    rn = revision(2, "receive_note", supplier={"name":"ACME"})
    assert select_candidates(revision(), [rn], set()).status == "selected"


def test_missing_names_still_use_matching_abn():
    inv = revision(supplier={"name": None, "business_number": "12-34"})
    rn = revision(
        2,
        "receive_note",
        supplier={"name": None, "business_number": "1234"},
    )
    assert select_candidates(inv, [rn], set()).status == "selected"


def test_missing_names_and_abn_remain_unverified():
    inv = revision(supplier={"name": None, "business_number": None})
    rn = revision(
        2,
        "receive_note",
        supplier={"name": None, "business_number": None},
    )
    result = select_candidates(inv, [rn], set())
    assert result.status == "needs_selection"
    assert "SUPPLIER_UNVERIFIED" in result.candidates[0].reason_codes


def test_non_receiving_ignored_and_no_input_mutation():
    inv = revision()
    original = inv.model_dump()
    assert select_candidates(inv, [revision(2)], set()).candidates == []
    assert inv.model_dump() == original


def test_highest_without_po_needs_twenty_point_gap():
    items = [dict(description=str(n), sku=str(n), unit="bag", quantity="1") for n in range(4)]
    inv = revision(purchase_order_number=None, items=items)
    best = revision(2,"receive_note",purchase_order_number=None,items=items)
    near = revision(3,"receive_note",purchase_order_number=None,items=items[:3])
    assert select_candidates(inv,[best,near],set()).status == "needs_selection"
    distant = revision(3,"receive_note",purchase_order_number=None,items=items[:1],document_date="2026-01-09")
    proposal = select_candidates(inv,[distant,best],set())
    assert [c.score for c in proposal.candidates] == [60,40]
    assert proposal.selected_document_ids == [best.document_id]


def test_supplier_blocking_issue_prevents_auto_selection():
    inv = revision()
    inv = RevisionView.model_validate({**inv.model_dump(),"validation_issues":[dict(rule_code="SUPPLIER_CONFLICT",severity="blocking",field_path="supplier.name",message="bad")]})
    result = select_candidates(inv,[revision(2,"receive_note")],set())
    assert result.status == "needs_selection"
    assert "SUPPLIER_UNVERIFIED" in result.candidates[0].reason_codes
