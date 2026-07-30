from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.domain.documents import DocumentType
from app.domain.extraction_tasks import ExtractionStatus, ExtractionTask
from app.infra.database import Base
from app.infra.postgres_task_repository import PostgresExtractionTaskRepository


def test_repository_round_trip() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    repository = PostgresExtractionTaskRepository(factory)
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
        status=ExtractionStatus.UPLOADED,
        created_at=now,
        updated_at=now,
    )

    repository.create(task)
    loaded = repository.get(task.task_id)

    assert loaded is not None
    assert loaded.task_id == task.task_id
    assert loaded.document_type == DocumentType.INVOICE
    assert loaded.status == ExtractionStatus.UPLOADED
    assert repository.list_recent() == [loaded]
