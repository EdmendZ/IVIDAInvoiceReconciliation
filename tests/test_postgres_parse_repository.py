from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.domain.documents import DocumentType
from app.domain.extraction_runs import ExtractionRun, ExtractionRunStatus
from app.domain.extraction_tasks import ExtractionStatus, ExtractionTask
from app.domain.parse_results import ParseResultRecord
from app.infra.database import Base
from app.infra.postgres_extraction_run_repository import (
    PostgresExtractionRunRepository,
)
from app.infra.postgres_parse_repository import PostgresParseResultRepository
from app.infra.postgres_task_repository import PostgresExtractionTaskRepository


def test_claim_and_parse_result_round_trip() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    tasks = PostgresExtractionTaskRepository(factory)
    runs = PostgresExtractionRunRepository(factory)
    parses = PostgresParseResultRepository(factory)
    now = datetime.now(UTC)
    task = ExtractionTask(
        task_id="00000000-0000-0000-0000-000000000001",
        document_type=DocumentType.INVOICE,
        original_filename="invoice.pdf",
        content_type="application/pdf",
        size_bytes=20,
        sha256="a" * 64,
        storage_bucket="test-bucket",
        storage_object_key="invoice/task/original/invoice.pdf",
        status=ExtractionStatus.EXTRACTING,
        created_at=now,
        updated_at=now,
    )
    run = ExtractionRun(
        run_id="00000000-0000-0000-0000-000000000002",
        task_id=task.task_id,
        provider="mineru",
        model_name="vlm",
        status=ExtractionRunStatus.QUEUED,
        next_attempt_at=now,
        started_at=now,
        created_at=now,
    )
    tasks.create(task)
    runs.create(run)

    claimed = runs.claim_next(worker_id="worker-1", lease_seconds=60, now=now)
    assert claimed is not None
    assert claimed.run_id == run.run_id
    assert claimed.lease_owner == "worker-1"
    assert runs.get_latest_for_task(task.task_id).run_id == run.run_id

    record = ParseResultRecord(
        parse_result_id="00000000-0000-0000-0000-000000000003",
        run_id=run.run_id,
        remote_job_id="batch-123",
        artifact_object_key="invoice/result.zip",
        markdown="# TAX INVOICE",
        content_blocks=[{"block_id": "1"}],
        tables=[],
        page_count=1,
        created_at=now,
    )
    parses.create(record)
    loaded = parses.get_for_run(run.run_id)
    assert loaded is not None
    assert loaded.page_count == 1
