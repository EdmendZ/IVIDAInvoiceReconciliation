from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.infra.database import Base
from app.infra.postgres_worker_runtime_repository import (
    PostgresWorkerRuntimeRepository,
)
from app.services.runtime_status_service import RuntimeStatusService


def _repository() -> PostgresWorkerRuntimeRepository:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    return PostgresWorkerRuntimeRepository(factory)


def test_latest_heartbeat_is_returned_and_updated() -> None:
    repository = _repository()
    first = datetime(2026, 7, 31, 8, 0, tzinfo=UTC)
    repository.heartbeat(worker_id="worker-a", version="0.1.0", now=first)
    repository.heartbeat(
        worker_id="worker-a",
        version="0.2.0",
        now=first + timedelta(seconds=10),
    )

    latest = repository.latest()

    assert latest is not None
    assert latest.worker_id == "worker-a"
    assert latest.version == "0.2.0"
    assert latest.started_at == first
    assert latest.last_seen_at == first + timedelta(seconds=10)


def test_runtime_marks_stale_worker_offline() -> None:
    repository = _repository()
    now = datetime(2026, 7, 31, 8, 0, tzinfo=UTC)
    repository.heartbeat(worker_id="worker-a", version="0.1.0", now=now)
    service = RuntimeStatusService(repository, offline_after_seconds=30)

    assert service.status(now=now + timedelta(seconds=30)).worker == "online"
    assert service.status(now=now + timedelta(seconds=31)).worker == "offline"
