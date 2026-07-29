from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.domain.document_drafts import DocumentDraft, DraftValidationState
from app.domain.documents import DocumentType
from app.domain.extraction_runs import ExtractionRun, ExtractionRunStatus
from app.domain.extraction_tasks import ExtractionStatus, ExtractionTask
from app.domain.normalization import FieldEvidence
from app.domain.validation import IssueSeverity, ValidationIssue
from app.infra.database import Base
from app.infra.postgres_draft_repository import PostgresDocumentDraftRepository
from app.infra.postgres_extraction_run_repository import (
    PostgresExtractionRunRepository,
)
from app.infra.postgres_task_repository import PostgresExtractionTaskRepository


def test_draft_evidence_and_issue_round_trip() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    now = datetime.now(UTC)
    task = ExtractionTask(
        task_id="00000000-0000-0000-0000-000000000001",
        document_type=DocumentType.INVOICE,
        original_filename="invoice.pdf",
        content_type="application/pdf",
        size_bytes=20,
        sha256="a" * 64,
        storage_bucket="test",
        storage_object_key="invoice.pdf",
        status=ExtractionStatus.EXTRACTING,
        created_at=now,
        updated_at=now,
    )
    run = ExtractionRun(
        run_id="00000000-0000-0000-0000-000000000002",
        task_id=task.task_id,
        provider="mineru",
        model_name="vlm",
        status=ExtractionRunStatus.NORMALIZING,
        started_at=now,
        created_at=now,
    )
    PostgresExtractionTaskRepository(factory).create(task)
    PostgresExtractionRunRepository(factory).create(run)
    repository = PostgresDocumentDraftRepository(factory)
    draft = DocumentDraft(
        draft_id="00000000-0000-0000-0000-000000000003",
        run_id=run.run_id,
        task_id=task.task_id,
        document_type=DocumentType.INVOICE,
        normalized_json={"document_number": "INV-1"},
        validation_state=DraftValidationState.BLOCKED,
        created_at=now,
        updated_at=now,
    )
    repository.create_with_evidence_and_issues(
        draft,
        [
            FieldEvidence(
                field_path="document_number",
                value="INV-1",
                page=1,
                source_text="Invoice INV-1",
            )
        ],
        [
            ValidationIssue(
                rule_code="PO_MISSING",
                severity=IssueSeverity.WARNING,
                field_path="purchase_order_number",
                message="Missing",
            )
        ],
    )
    loaded = repository.get_for_run(run.run_id)
    assert loaded is not None
    assert loaded.draft.normalized_json["document_number"] == "INV-1"
    assert loaded.evidence[0].page == 1
    assert loaded.issues[0].rule_code == "PO_MISSING"
