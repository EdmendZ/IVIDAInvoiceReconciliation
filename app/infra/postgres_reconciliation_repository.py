"""核对聚合的 PostgreSQL 事务写入。"""

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.domain.reconciliation_records import ReconciliationRecord
from app.infra.database_models import (
    ReconciliationLineResultRow,
    ReconciliationReceiveNoteRow,
    ReconciliationRow,
)


class PostgresReconciliationRepository:
    """在一个事务中保存头、参与版本关系和逐行结果。"""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def create(self, record: ReconciliationRecord) -> ReconciliationRecord:
        """原子持久化完整核对；任一插入失败时上下文会回滚。"""

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
                        line_result_id=str(uuid4()),
                        reconciliation_id=record.reconciliation_id,
                        line_index=index,
                        result_json=line.model_dump(mode="json"),
                    )
                    for index, line in enumerate(record.result.lines)
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
                    "created_at": row.created_at,
                }
            )
