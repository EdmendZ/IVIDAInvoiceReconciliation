"""ExtractionTask 的 PostgreSQL Repository。"""

from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from app.domain.extraction_tasks import ExtractionStatus
from app.domain.extraction_tasks import ExtractionTask
from app.infra.database_models import ExtractionTaskRow


class PostgresExtractionTaskRepository:
    """保存上传元数据并维护文件级状态摘要。"""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def create(self, task: ExtractionTask) -> None:
        """插入新文件身份；对象存储写入已在上传服务中先完成。"""
        row = ExtractionTaskRow(**task.model_dump(mode="python"))
        with self._session_factory() as session:
            session.add(row)
            session.commit()

    def get(self, task_id: str) -> ExtractionTask | None:
        """按稳定 Task ID 读取文件级状态，不加载历次 Run。"""
        with self._session_factory() as session:
            row = session.get(ExtractionTaskRow, task_id)
            if row is None:
                return None
            return ExtractionTask.model_validate(
                {
                    "task_id": row.task_id,
                    "document_type": row.document_type,
                    "original_filename": row.original_filename,
                    "content_type": row.content_type,
                    "size_bytes": row.size_bytes,
                    "sha256": row.sha256,
                    "storage_bucket": row.storage_bucket,
                    "storage_object_key": row.storage_object_key,
                    "purchase_order_hint": row.purchase_order_hint,
                    "status": row.status,
                    "error_message": row.error_message,
                    "created_at": row.created_at,
                    "updated_at": row.updated_at,
                }
            )

    def list_recent(self, limit: int = 100) -> list[ExtractionTask]:
        """按上传时间倒序返回后台列表所需的最近任务。"""
        with self._session_factory() as session:
            rows = session.execute(
                select(ExtractionTaskRow)
                .order_by(ExtractionTaskRow.created_at.desc())
                .limit(limit)
            ).scalars()
            return [self._to_domain(row) for row in rows]

    def update_status(
        self,
        task_id: str,
        status: ExtractionStatus,
        error_message: str | None = None,
    ) -> None:
        """更新 Task 当前状态和安全错误消息，不改动文件身份字段。"""

        with self._session_factory() as session:
            session.execute(
                update(ExtractionTaskRow)
                .where(ExtractionTaskRow.task_id == task_id)
                .values(
                    status=status.value,
                    error_message=error_message,
                    updated_at=datetime.now(UTC),
                )
            )
            session.commit()

    @staticmethod
    def _to_domain(row: ExtractionTaskRow) -> ExtractionTask:
        return ExtractionTask.model_validate(
            {
                column.name: getattr(row, column.name)
                for column in ExtractionTaskRow.__table__.columns
            }
        )
