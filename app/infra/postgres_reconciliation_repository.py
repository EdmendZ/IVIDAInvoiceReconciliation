"""核对聚合的 PostgreSQL 事务写入。"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.domain.reconciliation_records import (
    ReconciliationPersistenceBundle,
    ReconciliationRecord,
)
from app.infra.database_models import (
    CaseActionRow,
    CaseItemRow,
    ReconciliationCaseRow,
    ReconciliationLineResultRow,
    ReconciliationReceiveNoteRow,
    ReconciliationRow,
)


class PostgresReconciliationRepository:
    """在一个事务中保存头、参与版本关系和逐行结果。"""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def create(
        self,
        bundle: ReconciliationPersistenceBundle,
    ) -> ReconciliationRecord:
        """原子持久化完整核对；任一插入失败时上下文会回滚。"""

        record = bundle.record
        if len(bundle.line_result_ids) != len(record.result.lines):
            raise ValueError("One line_result_id is required for every result line")
        with self._session_factory() as session:
            # 三组记录共同表达一次核对，不能分开 commit 造成部分成功。
            session.add(
                ReconciliationRow(
                    reconciliation_id=record.reconciliation_id,
                    invoice_version_id=record.invoice_version_id,
                    result_json=record.result.model_dump(mode="json"),
                    created_by=record.created_by,
                    created_at=record.created_at,
                )
            )
            session.add_all(
                [
                    ReconciliationReceiveNoteRow(
                        reconciliation_id=record.reconciliation_id,
                        receive_note_version_id=version_id,
                    )
                    for version_id in record.receive_note_version_ids
                ]
            )
            session.add_all(
                [
                    ReconciliationLineResultRow(
                        line_result_id=line_result_id,
                        reconciliation_id=record.reconciliation_id,
                        line_index=index,
                        result_json=line.model_dump(mode="json"),
                    )
                    for index, (line_result_id, line) in enumerate(
                        zip(bundle.line_result_ids, record.result.lines, strict=True)
                    )
                ]
            )
            if bundle.case is not None:
                case = bundle.case.case
                session.add(
                    ReconciliationCaseRow(
                        case_id=case.case_id,
                        reconciliation_id=case.reconciliation_id,
                        status=case.status.value,
                        assignee_user_id=case.assignee_user_id,
                        revision=case.revision,
                        created_by=case.created_by,
                        created_at=case.created_at,
                        claimed_at=case.claimed_at,
                        submitted_at=case.submitted_at,
                        completed_at=case.completed_at,
                    )
                )
                session.add_all(
                    [
                        CaseItemRow(
                            item_id=item.item_id,
                            case_id=item.case_id,
                            item_type=item.item_type.value,
                            line_result_id=item.line_result_id,
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
                        for item in bundle.case.items
                    ]
                )
                session.add_all(
                    [
                        CaseActionRow(
                            action_id=action.action_id,
                            case_id=action.case_id,
                            item_id=action.item_id,
                            actor_user_id=action.actor_user_id,
                            action=action.action.value,
                            old_value=action.model_dump(mode="json")["old_value"],
                            new_value=action.model_dump(mode="json")["new_value"],
                            reason=action.reason,
                            created_at=action.created_at,
                        )
                        for action in bundle.case.actions
                    ]
                )
            session.commit()
        return record

    def get(self, reconciliation_id: str) -> ReconciliationRecord | None:
        """读取创建时保存的完整结果快照，供审计查看和导出复用。"""

        with self._session_factory() as session:
            row = session.get(ReconciliationRow, reconciliation_id)
            if row is None:
                return None
            receive_note_ids = list(
                session.scalars(
                    select(ReconciliationReceiveNoteRow.receive_note_version_id)
                    .where(
                        ReconciliationReceiveNoteRow.reconciliation_id
                        == reconciliation_id
                    )
                    .order_by(
                        ReconciliationReceiveNoteRow.receive_note_version_id
                    )
                )
            )
            return ReconciliationRecord.model_validate(
                {
                    "reconciliation_id": row.reconciliation_id,
                    "invoice_version_id": row.invoice_version_id,
                    "receive_note_version_ids": receive_note_ids,
                    "result": row.result_json,
                    "created_by": row.created_by,
                    "created_at": _utc(row.created_at),
                }
            )


def _utc(value: datetime) -> datetime:
    """SQLite drops timezone offsets; restore UTC for domain equality."""

    return value.replace(tzinfo=UTC) if value.tzinfo is None else value
