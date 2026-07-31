from datetime import UTC, datetime, timedelta

from app.domain.worker_runtime import RuntimeStatus
from app.services.ports import WorkerRuntimeRepository


class RuntimeStatusService:
    def __init__(
        self,
        repository: WorkerRuntimeRepository,
        *,
        offline_after_seconds: int = 30,
    ) -> None:
        self._repository = repository
        self._offline_after = timedelta(seconds=offline_after_seconds)

    def status(self, *, now: datetime | None = None) -> RuntimeStatus:
        current = now or datetime.now(UTC)
        heartbeat = self._repository.latest()
        if heartbeat is None:
            return RuntimeStatus(worker="offline")
        online = current - heartbeat.last_seen_at <= self._offline_after
        return RuntimeStatus(
            worker="online" if online else "offline",
            worker_last_seen_at=heartbeat.last_seen_at,
            worker_version=heartbeat.version,
        )
