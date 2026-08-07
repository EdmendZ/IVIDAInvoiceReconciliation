from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.domain.reconciliation import (
    LineComparison,
    MatchStatus,
    ReconciliationResult,
    ReconciliationSummary,
)
from app.domain.reconciliation_cases import (
    CaseActionType,
    CaseItem,
    CaseItemType,
    CaseStatus,
    ResolutionType,
)
from app.domain.reconciliation_records import ReconciliationRecord
from app.services.reconciliation_case_factory import build_case_bundle


NOW = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)


def line(status: str) -> LineComparison:
    return LineComparison(
        match_key="SKU-1",
        sku="SKU-1",
        description="Item",
        invoice_quantity=Decimal("1"),
        received_quantity=Decimal("1"),
        quantity_difference=Decimal("0"),
        invoice_unit_price=Decimal("1"),
        received_unit_price=Decimal("1"),
        unit_price_difference=Decimal("0"),
        invoice_amount=Decimal("1"),
        received_amount=Decimal("1"),
        amount_difference=Decimal("0"),
        status=MatchStatus(status),
    )


def reconciliation_record(
    *,
    requires_review: bool,
    lines: list[LineComparison],
    purchase_order_match: bool | None = True,
    currency_match: bool = True,
) -> ReconciliationRecord:
    return ReconciliationRecord(
        reconciliation_id="reconciliation-1",
        invoice_version_id="invoice-version-1",
        receive_note_version_ids=["receive-note-version-1"],
        result=ReconciliationResult(
            invoice_number="INV-1",
            receive_note_numbers=["RN-1"],
            purchase_order_match=purchase_order_match,
            currency_match=currency_match,
            lines=lines,
            summary=ReconciliationSummary(
                total_lines=len(lines),
                exact_lines=sum(item.status == MatchStatus.EXACT for item in lines),
                tolerance_lines=sum(
                    item.status == MatchStatus.WITHIN_TOLERANCE for item in lines
                ),
                mismatch_lines=sum(item.status == MatchStatus.MISMATCH for item in lines),
                invoice_only_lines=sum(
                    item.status == MatchStatus.INVOICE_ONLY for item in lines
                ),
                receive_note_only_lines=sum(
                    item.status == MatchStatus.RECEIVE_NOTE_ONLY for item in lines
                ),
                requires_review=requires_review,
            ),
        ),
        created_by="user-1",
        created_at=NOW,
    )


def test_clean_reconciliation_does_not_create_case() -> None:
    record = reconciliation_record(requires_review=False, lines=[])

    assert build_case_bundle(record, [], now=NOW) is None


def test_abnormal_result_creates_line_and_header_items() -> None:
    record = reconciliation_record(
        requires_review=True,
        purchase_order_match=False,
        currency_match=False,
        lines=[line("mismatch"), line("exact"), line("within_tolerance")],
    )

    bundle = build_case_bundle(record, ["line-0", "line-1", "line-2"], now=NOW)

    assert bundle is not None
    assert bundle.case.status == CaseStatus.UNASSIGNED
    assert [item.item_type for item in bundle.items] == [
        CaseItemType.LINE,
        CaseItemType.PURCHASE_ORDER_CONFLICT,
        CaseItemType.CURRENCY_CONFLICT,
    ]
    assert bundle.items[0].line_result_id == "line-0"
    assert [action.action for action in bundle.actions] == [CaseActionType.CREATED]


@pytest.mark.parametrize("line_result_ids", [[], ["line-0", "line-1"]])
def test_factory_requires_one_persisted_id_per_result_line(
    line_result_ids: list[str],
) -> None:
    record = reconciliation_record(
        requires_review=True,
        lines=[line("mismatch")],
    )

    with pytest.raises(ValueError, match="One line_result_id"):
        build_case_bundle(record, line_result_ids, now=NOW)


def test_review_required_result_must_have_an_actionable_item() -> None:
    record = reconciliation_record(
        requires_review=True,
        lines=[line("exact")],
    )

    with pytest.raises(ValueError, match="must create a case item"):
        build_case_bundle(record, ["line-0"], now=NOW)


def test_case_item_rejects_a_blank_non_null_resolution_note() -> None:
    with pytest.raises(ValueError, match="resolution_note must not be blank"):
        CaseItem(
            item_id="item-1",
            case_id="case-1",
            item_type=CaseItemType.PURCHASE_ORDER_CONFLICT,
            resolution_type=ResolutionType.BUSINESS_EXCEPTION,
            resolution_note="  ",
            updated_at=NOW,
        )
