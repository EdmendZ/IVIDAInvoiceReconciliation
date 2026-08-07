"""PostgreSQL persistence and read models for reconciliation cases."""

from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.domain.reconciliation_cases import (
    AssignmentFilter,
    CaseAction,
    CaseActionType,
    CaseActionView,
    CaseDetail,
    CaseItem,
    CaseLineResult,
    CaseListQuery,
    CasePage,
    CaseStatus,
    CaseSummary,
    ReconciliationCase,
    ReconciliationCaseBundle,
)
from app.domain.reconciliation_records import ReconciliationRecord
from app.infra.database_models import (
    AdminUserRow,
    CaseActionRow,
    CaseItemRow,
    ReconciliationCaseRow,
    ReconciliationLineResultRow,
    ReconciliationReceiveNoteRow,
    ReconciliationRow,
)
from app.services.reconciliation_case_service import CaseError


class PostgresReconciliationCaseRepository:
    """Read cases and atomically persist one optimistic case mutation."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get_bundle(self, case_id: str) -> ReconciliationCaseBundle | None:
        with self._session_factory() as session:
            row = session.get(ReconciliationCaseRow, case_id)
            return self._load_bundle(session, row) if row is not None else None

    def get_by_reconciliation(
        self,
        reconciliation_id: str,
    ) -> ReconciliationCaseBundle | None:
        """Resolve the optional case created alongside a reconciliation."""

        with self._session_factory() as session:
            row = session.scalar(
                select(ReconciliationCaseRow).where(
                    ReconciliationCaseRow.reconciliation_id == reconciliation_id
                )
            )
            return self._load_bundle(session, row) if row is not None else None

    def list_cases(self, query: CaseListQuery, user_id: str) -> CasePage:
        invoice_number = ReconciliationRow.result_json[
            "invoice_number"
        ].as_string()
        conditions = []
        if query.statuses:
            conditions.append(
                ReconciliationCaseRow.status.in_(
                    [status.value for status in query.statuses]
                )
            )
        if query.assignment == AssignmentFilter.MINE:
            conditions.append(ReconciliationCaseRow.assignee_user_id == user_id)
        elif query.assignment == AssignmentFilter.UNASSIGNED:
            conditions.append(ReconciliationCaseRow.assignee_user_id.is_(None))
        if query.invoice_number is not None:
            conditions.append(
                invoice_number.startswith(query.invoice_number, autoescape=True)
            )

        actionable_count = (
            select(func.count(CaseItemRow.item_id))
            .where(CaseItemRow.case_id == ReconciliationCaseRow.case_id)
            .correlate(ReconciliationCaseRow)
            .scalar_subquery()
        )
        statement = (
            select(
                ReconciliationCaseRow,
                ReconciliationRow.result_json,
                AdminUserRow.username,
                actionable_count,
            )
            .join(
                ReconciliationRow,
                ReconciliationRow.reconciliation_id
                == ReconciliationCaseRow.reconciliation_id,
            )
            .outerjoin(
                AdminUserRow,
                AdminUserRow.user_id == ReconciliationCaseRow.assignee_user_id,
            )
            .where(*conditions)
            .order_by(
                ReconciliationCaseRow.created_at.asc(),
                ReconciliationCaseRow.case_id.asc(),
            )
            .offset((query.page - 1) * query.page_size)
            .limit(query.page_size)
        )
        count_statement = (
            select(func.count())
            .select_from(ReconciliationCaseRow)
            .join(
                ReconciliationRow,
                ReconciliationRow.reconciliation_id
                == ReconciliationCaseRow.reconciliation_id,
            )
            .where(*conditions)
        )
        with self._session_factory() as session:
            total = int(session.scalar(count_statement) or 0)
            rows = session.execute(statement).all()
            items = [
                CaseSummary(
                    case=_case_model(case_row),
                    invoice_number=result_json["invoice_number"],
                    receive_note_numbers=list(
                        result_json["receive_note_numbers"]
                    ),
                    actionable_count=count,
                    assignee_username=username,
                )
                for case_row, result_json, username, count in rows
            ]
        return CasePage(
            items=items,
            page=query.page,
            page_size=query.page_size,
            total=total,
        )

    def get_detail(self, case_id: str) -> CaseDetail | None:
        """Return a self-consistent detail, retrying a concurrent revision change."""

        for _attempt in range(3):
            detail = self._get_detail_unchecked(case_id)
            if detail is None:
                return None
            with self._session_factory() as session:
                current_revision = session.scalar(
                    select(ReconciliationCaseRow.revision).where(
                        ReconciliationCaseRow.case_id == case_id
                    )
                )
            if current_revision == detail.case.revision:
                return detail
        raise CaseError(
            "CASE_REVISION_CONFLICT",
            "Case changed repeatedly while loading; refresh and retry",
        )

    def _get_detail_unchecked(self, case_id: str) -> CaseDetail | None:
        """Load one candidate detail; the caller verifies its ending revision."""

        with self._session_factory() as session:
            joined = session.execute(
                select(
                    ReconciliationCaseRow,
                    ReconciliationRow,
                    AdminUserRow.username,
                )
                .join(
                    ReconciliationRow,
                    ReconciliationRow.reconciliation_id
                    == ReconciliationCaseRow.reconciliation_id,
                )
                .outerjoin(
                    AdminUserRow,
                    AdminUserRow.user_id
                    == ReconciliationCaseRow.assignee_user_id,
                )
                .where(ReconciliationCaseRow.case_id == case_id)
            ).one_or_none()
            if joined is None:
                return None
            case_row, reconciliation_row, assignee_username = joined
            items = self._load_items(session, case_id)
            line_rows = list(
                session.scalars(
                    select(ReconciliationLineResultRow)
                    .where(
                        ReconciliationLineResultRow.reconciliation_id
                        == reconciliation_row.reconciliation_id
                    )
                    .order_by(
                        ReconciliationLineResultRow.line_index.asc(),
                        ReconciliationLineResultRow.line_result_id.asc(),
                    )
                )
            )
            action_rows = session.execute(
                select(CaseActionRow, AdminUserRow.username)
                .join(
                    AdminUserRow,
                    AdminUserRow.user_id == CaseActionRow.actor_user_id,
                )
                .where(CaseActionRow.case_id == case_id)
                .order_by(
                    CaseActionRow.created_at.asc(),
                    CaseActionRow.action_id.asc(),
                )
            ).all()
            receive_note_ids = list(
                session.scalars(
                    select(ReconciliationReceiveNoteRow.receive_note_version_id)
                    .where(
                        ReconciliationReceiveNoteRow.reconciliation_id
                        == reconciliation_row.reconciliation_id
                    )
                    .order_by(
                        ReconciliationReceiveNoteRow.receive_note_version_id.asc()
                    )
                )
            )
            reconciliation = ReconciliationRecord.model_validate(
                {
                    "reconciliation_id": reconciliation_row.reconciliation_id,
                    "invoice_version_id": reconciliation_row.invoice_version_id,
                    "receive_note_version_ids": receive_note_ids,
                    "result": reconciliation_row.result_json,
                    "created_by": reconciliation_row.created_by,
                    "created_at": _utc(reconciliation_row.created_at),
                }
            )
            return CaseDetail(
                case=_case_model(case_row),
                items=items,
                actions=[
                    CaseActionView(
                        action=_action_model(action_row),
                        actor_username=username,
                    )
                    for action_row, username in action_rows
                ],
                reconciliation=reconciliation,
                assignee_username=assignee_username,
                line_results=[
                    CaseLineResult(
                        line_result_id=line_row.line_result_id,
                        line=line_row.result_json,
                    )
                    for line_row in line_rows
                ],
            )

    def get_detail_for_bundle(
        self,
        bundle: ReconciliationCaseBundle,
    ) -> CaseDetail:
        """Hydrate immutable/display data around one committed mutation result."""

        case = bundle.case
        with self._session_factory() as session:
            reconciliation_row = session.get(
                ReconciliationRow,
                case.reconciliation_id,
            )
            if reconciliation_row is None:
                raise CaseError("CASE_NOT_FOUND", "Case was not found")
            receive_note_ids = list(
                session.scalars(
                    select(ReconciliationReceiveNoteRow.receive_note_version_id)
                    .where(
                        ReconciliationReceiveNoteRow.reconciliation_id
                        == case.reconciliation_id
                    )
                    .order_by(
                        ReconciliationReceiveNoteRow.receive_note_version_id.asc()
                    )
                )
            )
            line_rows = list(
                session.scalars(
                    select(ReconciliationLineResultRow)
                    .where(
                        ReconciliationLineResultRow.reconciliation_id
                        == case.reconciliation_id
                    )
                    .order_by(
                        ReconciliationLineResultRow.line_index.asc(),
                        ReconciliationLineResultRow.line_result_id.asc(),
                    )
                )
            )
            actor_ids = {action.actor_user_id for action in bundle.actions}
            if case.assignee_user_id is not None:
                actor_ids.add(case.assignee_user_id)
            usernames = dict(
                session.execute(
                    select(AdminUserRow.user_id, AdminUserRow.username).where(
                        AdminUserRow.user_id.in_(actor_ids)
                    )
                ).all()
            )

        reconciliation = ReconciliationRecord.model_validate(
            {
                "reconciliation_id": reconciliation_row.reconciliation_id,
                "invoice_version_id": reconciliation_row.invoice_version_id,
                "receive_note_version_ids": receive_note_ids,
                "result": reconciliation_row.result_json,
                "created_by": reconciliation_row.created_by,
                "created_at": _utc(reconciliation_row.created_at),
            }
        )
        return CaseDetail(
            case=case,
            items=bundle.items,
            actions=[
                CaseActionView(
                    action=action,
                    actor_username=usernames[action.actor_user_id],
                )
                for action in bundle.actions
            ],
            reconciliation=reconciliation,
            assignee_username=(
                usernames.get(case.assignee_user_id)
                if case.assignee_user_id is not None
                else None
            ),
            line_results=[
                CaseLineResult(
                    line_result_id=line_row.line_result_id,
                    line=line_row.result_json,
                )
                for line_row in line_rows
            ],
        )

    def save_case_mutation(
        self,
        bundle: ReconciliationCaseBundle,
        action: CaseAction,
        *,
        expected_revision: int,
    ) -> ReconciliationCaseBundle:
        """Conditionally advance one case, optionally update one item, and audit once."""

        case = bundle.case
        with self._session_factory() as session:
            mutation = update(ReconciliationCaseRow).where(
                ReconciliationCaseRow.case_id == case.case_id,
                ReconciliationCaseRow.revision == expected_revision,
            )
            if action.action == CaseActionType.CLAIMED:
                mutation = mutation.where(
                    ReconciliationCaseRow.status == CaseStatus.UNASSIGNED.value,
                    ReconciliationCaseRow.assignee_user_id.is_(None),
                )
            updated = session.execute(
                mutation
                .values(
                    status=case.status.value,
                    assignee_user_id=case.assignee_user_id,
                    revision=expected_revision + 1,
                    claimed_at=case.claimed_at,
                    submitted_at=case.submitted_at,
                    completed_at=case.completed_at,
                )
            )
            if updated.rowcount != 1:
                if action.action == CaseActionType.CLAIMED:
                    current = session.execute(
                        select(
                            ReconciliationCaseRow.status,
                            ReconciliationCaseRow.assignee_user_id,
                        ).where(ReconciliationCaseRow.case_id == case.case_id)
                    ).one_or_none()
                    if current is not None and (
                        current.status != CaseStatus.UNASSIGNED.value
                        or current.assignee_user_id is not None
                    ):
                        raise CaseError(
                            "CASE_ALREADY_CLAIMED",
                            "Case has already been claimed",
                        )
                raise CaseError(
                    "CASE_REVISION_CONFLICT",
                    "Case has changed; refresh and retry",
                )

            if action.item_id is not None:
                item = next(
                    (
                        candidate
                        for candidate in bundle.items
                        if candidate.item_id == action.item_id
                    ),
                    None,
                )
                if item is None:
                    raise CaseError("CASE_ITEM_NOT_FOUND", "Case item was not found")
                item_update = session.execute(
                    update(CaseItemRow)
                    .where(
                        CaseItemRow.item_id == item.item_id,
                        CaseItemRow.case_id == case.case_id,
                    )
                    .values(
                        resolution_type=(
                            item.resolution_type.value
                            if item.resolution_type is not None
                            else None
                        ),
                        resolution_note=item.resolution_note,
                        resolved_by=item.resolved_by,
                        resolved_at=item.resolved_at,
                        updated_at=item.updated_at,
                    )
                )
                if item_update.rowcount != 1:
                    raise CaseError("CASE_ITEM_NOT_FOUND", "Case item was not found")

            session.add(_action_row(action))
            session.commit()

        saved_case = case.model_copy(update={"revision": expected_revision + 1})
        actions = sorted(
            [*bundle.actions, action],
            key=lambda candidate: (candidate.created_at, candidate.action_id),
        )
        return bundle.model_copy(update={"case": saved_case, "actions": actions})

    @staticmethod
    def _load_bundle(
        session: Session,
        case_row: ReconciliationCaseRow,
    ) -> ReconciliationCaseBundle:
        actions = list(
            session.scalars(
                select(CaseActionRow)
                .where(CaseActionRow.case_id == case_row.case_id)
                .order_by(
                    CaseActionRow.created_at.asc(),
                    CaseActionRow.action_id.asc(),
                )
            )
        )
        return ReconciliationCaseBundle(
            case=_case_model(case_row),
            items=PostgresReconciliationCaseRepository._load_items(
                session,
                case_row.case_id,
            ),
            actions=[_action_model(row) for row in actions],
        )

    @staticmethod
    def _load_items(session: Session, case_id: str) -> list[CaseItem]:
        rows = list(
            session.scalars(
                select(CaseItemRow)
                .where(CaseItemRow.case_id == case_id)
                .order_by(CaseItemRow.item_id.asc())
            )
        )
        return [_item_model(row) for row in rows]


def _case_model(row: ReconciliationCaseRow) -> ReconciliationCase:
    return ReconciliationCase(
        case_id=row.case_id,
        reconciliation_id=row.reconciliation_id,
        status=row.status,
        assignee_user_id=row.assignee_user_id,
        revision=row.revision,
        created_by=row.created_by,
        created_at=_utc(row.created_at),
        claimed_at=_utc_optional(row.claimed_at),
        submitted_at=_utc_optional(row.submitted_at),
        completed_at=_utc_optional(row.completed_at),
    )


def _item_model(row: CaseItemRow) -> CaseItem:
    return CaseItem(
        item_id=row.item_id,
        case_id=row.case_id,
        item_type=row.item_type,
        line_result_id=row.line_result_id,
        resolution_type=row.resolution_type,
        resolution_note=row.resolution_note,
        resolved_by=row.resolved_by,
        resolved_at=_utc_optional(row.resolved_at),
        updated_at=_utc(row.updated_at),
    )


def _action_model(row: CaseActionRow) -> CaseAction:
    return CaseAction(
        action_id=row.action_id,
        case_id=row.case_id,
        item_id=row.item_id,
        actor_user_id=row.actor_user_id,
        action=row.action,
        old_value=row.old_value,
        new_value=row.new_value,
        reason=row.reason,
        created_at=_utc(row.created_at),
    )


def _action_row(action: CaseAction) -> CaseActionRow:
    serialized = action.model_dump(mode="json")
    return CaseActionRow(
        action_id=action.action_id,
        case_id=action.case_id,
        item_id=action.item_id,
        actor_user_id=action.actor_user_id,
        action=action.action.value,
        old_value=serialized["old_value"],
        new_value=serialized["new_value"],
        reason=action.reason,
        created_at=action.created_at,
    )


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _utc_optional(value: datetime | None) -> datetime | None:
    return _utc(value) if value is not None else None
