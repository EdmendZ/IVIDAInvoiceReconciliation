"""Workspace worker process entrypoint."""
from __future__ import annotations

import signal
import threading

from app.core.config import get_settings
from app.domain.workspace import WorkspaceScopeKey
from app.infra.database import get_session_factory
from app.infra.postgres_workspace_repository import PostgresWorkspaceRepository
from app.workers.workspace_worker import WorkspaceWorker


def build_workspace_worker() -> WorkspaceWorker | None:
    settings = get_settings()
    if not settings.workspace_enabled:
        return None
    scope = WorkspaceScopeKey(
        tenant_id=settings.workspace_tenant_id,
        store_id=settings.workspace_store_id,
    )
    return WorkspaceWorker(
        PostgresWorkspaceRepository(get_session_factory()),
        scope,
    )


def main() -> None:
    stop_event = threading.Event()

    def request_stop(_signum=None, _frame=None) -> None:
        stop_event.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    worker = build_workspace_worker()
    if worker is None:
        return
    try:
        worker.run_forever(stop_event)
    except KeyboardInterrupt:
        stop_event.set()


if __name__ == "__main__":
    main()
