from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.domain.worker_runtime import WorkerHeartbeat
from app.infra.database_models import WorkerHeartbeatRow


class PostgresWorkerRuntimeRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def heartbeat(
        self,
        *,
        worker_id: str,
        version: str,
        now: datetime,
    ) -> None:
        with self._session_factory() as session:
            row = session.get(WorkerHeartbeatRow, worker_id)
            if row is None:
                session.add(
                    WorkerHeartbeatRow(
                        worker_id=worker_id,
                        version=version,
                        started_at=now,
                        last_seen_at=now,
                    )
                )
            else:
                row.version = version
                row.last_seen_at = now
            session.commit()

    def latest(self) -> WorkerHeartbeat | None:
        with self._session_factory() as session:
            row = session.execute(
                select(WorkerHeartbeatRow)
                .order_by(WorkerHeartbeatRow.last_seen_at.desc())
                .limit(1)
            ).scalar_one_or_none()
            if row is None:
                return None
            started_at = self._as_utc(row.started_at)
            last_seen_at = self._as_utc(row.last_seen_at)
            return WorkerHeartbeat(
                worker_id=row.worker_id,
                version=row.version,
                started_at=started_at,
                last_seen_at=last_seen_at,
            )

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
