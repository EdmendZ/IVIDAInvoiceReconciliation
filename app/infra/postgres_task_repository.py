from sqlalchemy.orm import Session, sessionmaker

from app.domain.extraction_tasks import ExtractionTask
from app.infra.database_models import ExtractionTaskRow


class PostgresExtractionTaskRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def create(self, task: ExtractionTask) -> None:
        row = ExtractionTaskRow(**task.model_dump(mode="python"))
        with self._session_factory() as session:
            session.add(row)
            session.commit()

    def get(self, task_id: str) -> ExtractionTask | None:
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
