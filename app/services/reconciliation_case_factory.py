"""Pure construction of reconciliation case aggregates from reconciliation results."""

from datetime import datetime
from uuid import uuid4

from app.domain.reconciliation import MatchStatus
from app.domain.reconciliation_cases import (
    CaseAction,
    CaseActionType,
    CaseItem,
    CaseItemType,
    CaseStatus,
    ReconciliationCase,
    ReconciliationCaseBundle,
)
from app.domain.reconciliation_records import ReconciliationRecord


ACTIONABLE = {
    MatchStatus.MISMATCH,
    MatchStatus.INVOICE_ONLY,
    MatchStatus.RECEIVE_NOTE_ONLY,
}


def header_item(case_id: str, item_type: CaseItemType, now: datetime) -> CaseItem:
    return CaseItem(
        item_id=str(uuid4()),
        case_id=case_id,
        item_type=item_type,
        updated_at=now,
    )


def created_action(case_id: str, actor_user_id: str, now: datetime) -> CaseAction:
    return CaseAction(
        action_id=str(uuid4()),
        case_id=case_id,
        actor_user_id=actor_user_id,
        action=CaseActionType.CREATED,
        created_at=now,
    )


def build_case_bundle(
    record: ReconciliationRecord,
    line_result_ids: list[str],
    *,
    now: datetime,
) -> ReconciliationCaseBundle | None:
    if len(line_result_ids) != len(record.result.lines):
        raise ValueError("One line_result_id is required for every result line")
    if not record.result.summary.requires_review:
        return None

    case_id = str(uuid4())
    items = [
        CaseItem(
            item_id=str(uuid4()),
            case_id=case_id,
            item_type=CaseItemType.LINE,
            line_result_id=line_result_ids[index],
            updated_at=now,
        )
        for index, line in enumerate(record.result.lines)
        if line.status in ACTIONABLE
    ]
    if record.result.purchase_order_match is False:
        items.append(header_item(case_id, CaseItemType.PURCHASE_ORDER_CONFLICT, now))
    if record.result.currency_match is False:
        items.append(header_item(case_id, CaseItemType.CURRENCY_CONFLICT, now))
    if not items:
        raise ValueError("A review-required reconciliation must create a case item")

    case = ReconciliationCase(
        case_id=case_id,
        reconciliation_id=record.reconciliation_id,
        status=CaseStatus.UNASSIGNED,
        assignee_user_id=None,
        revision=1,
        created_by=record.created_by,
        created_at=now,
    )
    action = created_action(case_id, record.created_by, now)
    return ReconciliationCaseBundle(case=case, items=items, actions=[action])
