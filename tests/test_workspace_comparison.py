from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

import pytest

from app.domain.workspace import RevisionView
from app.services.workspace_comparison import compare_workspace


def line(**updates):
    value = dict(description="Rice", sku="R1", quantity="10", unit="bag", unit_price="2", line_total="20")
    value.update(updates)
    return value


def revision(n=1, kind="invoice", **updates):
    payload = dict(document_type=kind, document_number="INV-1", supplier={"name":"Acme"}, items=[line()])
    payload.update(updates)
    return RevisionView(document_id=str(UUID(int=n)), revision_id=str(UUID(int=n+1000)), sequence=1,
                        origin="extracted", payload=payload, created_at=datetime(2026,1,1,tzinfo=timezone.utc))


def compare(left=None, right=None, **updates):
    return compare_workspace(revision(items=left or [line()]),
                             [revision(2,"receive_note",items=right or [line()], **updates)])


def test_po_one_to_many_quantity_six_plus_four_and_references():
    notes = [revision(3,"receive_note",items=[line(quantity="4",line_total="8")]),
             revision(2,"receive_note",items=[line(quantity="6",line_total="12")])]
    result = compare_workspace(revision(), notes)
    assert result.outcome == "consistent" and result.coverage == "full"
    assert result.lines[0].quantity.received_value == Decimal("10")
    assert result.lines[0].invoice_line_indexes == [0]
    assert [r.document_id for r in result.lines[0].receive_lines] == sorted(r.document_id for r in notes)
    assert result == compare_workspace(revision(), list(reversed(notes)))
    assert set(result.unverified_dimensions) == {"tax","document_total"}


def test_unknown_price_amount_is_quantity_only_not_zero_or_difference():
    result = compare(right=[line(unit_price=None,line_total=None)])
    assert result.outcome == "consistent" and result.coverage == "quantity_only"
    assert result.lines[0].price.received_value is None
    assert result.lines[0].price.difference is None
    assert result.lines[0].status == "unverified"
    assert result.summary.unverified_lines == 1
    assert set(result.unverified_dimensions) == {"price","amount","tax","document_total"}


def test_known_zero_price_is_verified():
    result = compare(left=[line(unit_price="0",line_total="0")],right=[line(unit_price="0",line_total=None)])
    assert result.coverage == "full"
    assert result.lines[0].amount.received_value == 0
    assert result.lines[0].price.status == "equal"


@pytest.mark.parametrize("unit,code", [(None,"UNIT_UNVERIFIED"),("carton","UNIT_CONFLICT"),("g","UNIT_CONFLICT")])
def test_unit_missing_or_conflicting_is_blocked(unit, code):
    result = compare(left=[line(unit="kg")],right=[line(unit=unit)])
    assert result.outcome == "blocked" and code in result.blocking_codes
    assert len(result.lines) == 2
    assert not any(row.invoice_line_indexes and row.receive_lines for row in result.lines)


def test_multiple_units_do_not_sum_incompatible_quantities():
    result = compare(left=[line(unit="kg"),line(unit="bag",quantity="2",line_total="4")],right=[line(unit="kg")])
    assert "UNIT_CONFLICT" in result.blocking_codes
    assert len(result.lines) == 2
    assert {row.quantity.invoice_value for row in result.lines} == {Decimal("10"),Decimal("2")}


@pytest.mark.parametrize("a,b", [("KGS"," kilograms "),("pcs","ea"),("litres","liter"),("ctn","cartons"),(" Special ","special")])
def test_unit_synonyms_and_unknown_exact_text(a,b):
    assert compare(left=[line(unit=a)],right=[line(unit=b)]).outcome == "consistent"


def test_chinese_keys_and_empty_key():
    result = compare(left=[line(sku=None,description="大米")],right=[line(sku=None,description="面粉")])
    assert {row.match_key for row in result.lines} == {"description:大米","description:面粉"}
    assert result.outcome == "difference" and result.coverage == "quantity_only"
    assert "EMPTY_ITEM_KEY" in compare(left=[line(sku=None,description="--")]).blocking_codes


def test_sku_and_description_never_silently_merge():
    result = compare(right=[line(sku=None)])
    assert {row.status for row in result.lines} == {"invoice_only","receive_only"}
    assert result.summary.different_lines == 2


def test_multiple_prices_unverified_but_amount_and_quantity_independent():
    result = compare(left=[line(quantity="5",unit_price="1",line_total="5"),line(quantity="5",unit_price="3",line_total="15")])
    assert result.coverage == "quantity_and_amount"
    assert result.outcome == "consistent"
    assert result.lines[0].price.status == "unverified"
    assert result.lines[0].price.reason_code == "MULTIPLE_PRICES"
    assert result.lines[0].invoice_line_indexes == [0,1]
    assert result.lines[0].amount.status == "equal"


@pytest.mark.parametrize("value,status", [("2.01","within_tolerance"),("2.0101","different")])
def test_price_decimal_boundary(value,status):
    result = compare(left=[line(quantity="1",line_total=None)],right=[line(quantity="1",unit_price=value,line_total=None)])
    assert result.lines[0].price.status == status
    assert result.lines[0].price.difference == Decimal("2")-Decimal(value)


@pytest.mark.parametrize("value,status", [("20.02","within_tolerance"),("20.0201","different")])
def test_amount_decimal_boundary(value,status):
    result = compare(right=[line(unit_price=None,line_total=value)])
    assert result.lines[0].amount.status == status
    assert result.lines[0].status == ("different" if status == "different" else "unverified")


def test_quantity_difference_and_price_unknown_priority():
    result = compare(right=[line(quantity="8",unit_price=None,line_total=None)])
    assert result.outcome == "difference"
    assert result.lines[0].status == "different"
    assert result.lines[0].quantity.difference == 2


def test_subject_currency_and_internal_validation_blocks():
    assert "SUPPLIER_CONFLICT" in compare(supplier={"name":"Other"}).blocking_codes
    assert "SUPPLIER_UNVERIFIED" in compare(supplier=None).blocking_codes
    assert "CURRENCY_CONFLICT" in compare(currency="USD").blocking_codes
    result = compare_workspace(revision(currency="USD"),[revision(2,"receive_note",currency="USD")])
    assert result.blocking_codes == ["UNSUPPORTED_CURRENCY"]
    assert "VALIDATION_BLOCKED" in compare(right=[line(line_total="25")]).blocking_codes


def test_revision_validation_issues_block_and_missing_po_only_warning():
    inv = revision()
    assert compare_workspace(inv,[revision(2,"receive_note")]).outcome == "consistent"
    inv = RevisionView.model_validate({**inv.model_dump(), "validation_issues":[dict(rule_code="CUSTOM", severity="blocking", field_path="supplier",message="bad")]})
    assert "VALIDATION_BLOCKED" in compare_workspace(inv,[revision(2,"receive_note")]).blocking_codes


def test_missing_invoice_number_blocked_and_no_receiving_not_consistent():
    assert "VALIDATION_BLOCKED" in compare_workspace(revision(document_number="---"),[revision(2,"receive_note")]).blocking_codes
    result = compare_workspace(revision(),[])
    assert result.outcome == "difference" and result.coverage == "quantity_only"


def test_no_mutation_and_partial_tax_not_blocking():
    inv = revision(items=[line(quantity="5",line_total="10",tax_amount="1"),line(quantity="5",line_total="10",tax_amount=None)],tax_total="2")
    original = inv.model_dump()
    assert compare_workspace(inv,[revision(2,"receive_note")]).outcome == "consistent"
    assert inv.model_dump() == original


def test_aggregate_unknown_price_or_amount_never_partially_sum():
    result = compare(right=[line(quantity="5",line_total="10"),line(quantity="5",unit_price=None,line_total=None)])
    assert result.lines[0].quantity.status == "equal"
    assert result.lines[0].price.received_value is None
    assert result.lines[0].amount.received_value is None
    assert result.coverage == "quantity_only"


def test_aggregate_known_amount_and_unknown_price_keeps_amount_coverage():
    result = compare(right=[line(quantity="5",line_total="10"),line(quantity="5",unit_price=None,line_total="10")])
    assert result.coverage == "quantity_and_amount"
    assert result.lines[0].amount.received_value == 20
    assert result.lines[0].price.reason_code is None
