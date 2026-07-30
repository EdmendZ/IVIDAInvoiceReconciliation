from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.domain.admin_users import (
    AdminRole,
    AdminUser,
    AuthenticatedUser,
)
from app.domain.document_drafts import DocumentDraft, DraftValidationState
from app.domain.documents import DocumentType
from app.domain.extraction_runs import ExtractionRun, ExtractionRunStatus
from app.domain.extraction_tasks import ExtractionStatus, ExtractionTask
from app.infra.database import Base
from app.infra.postgres_admin_repository import PostgresAdminRepository
from app.infra.postgres_draft_repository import PostgresDocumentDraftRepository
from app.infra.postgres_extraction_run_repository import (
    PostgresExtractionRunRepository,
)
from app.infra.postgres_review_repository import (
    ApprovedVersionImmutable,
    PostgresReviewRepository,
)
from app.infra.postgres_task_repository import PostgresExtractionTaskRepository
from app.services.review_service import (
    DocumentTypeConfirmationMismatch,
    ReviewConflict,
    ReviewService,
    UnresolvedBlockingIssues,
)
from app.services.validation_service import ValidationService


def _build_service():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    now = datetime.now(UTC)
    user = AdminUser(
        user_id="00000000-0000-0000-0000-000000000010",
        username="reviewer",
        password_hash="unused",
        role=AdminRole.REVIEWER,
        is_active=True,
        created_at=now,
    )
    PostgresAdminRepository(factory).create_user(user)
    task = ExtractionTask(
        task_id="00000000-0000-0000-0000-000000000001",
        document_type=DocumentType.INVOICE,
        original_filename="invoice.pdf",
        content_type="application/pdf",
        size_bytes=10,
        sha256="a" * 64,
        storage_bucket="test",
        storage_object_key="invoice.pdf",
        status=ExtractionStatus.READY_FOR_REVIEW,
        created_at=now,
        updated_at=now,
    )
    run = ExtractionRun(
        run_id="00000000-0000-0000-0000-000000000002",
        task_id=task.task_id,
        provider="mineru",
        model_name="vlm",
        status=ExtractionRunStatus.READY_FOR_REVIEW,
        started_at=now,
        created_at=now,
    )
    PostgresExtractionTaskRepository(factory).create(task)
    PostgresExtractionRunRepository(factory).create(run)
    drafts = PostgresDocumentDraftRepository(factory)
    drafts.create_with_evidence_and_issues(
        DocumentDraft(
            draft_id="00000000-0000-0000-0000-000000000003",
            run_id=run.run_id,
            task_id=task.task_id,
            document_type=DocumentType.INVOICE,
            normalized_json={
                "document_type": "invoice",
                "document_number": "INV-1",
                "purchase_order_number": "PO-1",
                "subtotal": "20.00",
                "tax_total": "2.00",
                "total": "22.00",
                "items": [
                    {
                        "description": "Mozzarella",
                        "quantity": "2",
                        "unit_price": "10.00",
                        "line_total": "20.00",
                        "tax_amount": "2.00",
                    }
                ],
            },
            validation_state=DraftValidationState.REVIEWABLE,
            created_at=now,
            updated_at=now,
        ),
        [],
        [],
    )
    reviews = PostgresReviewRepository(factory)
    service = ReviewService(
        review_repository=reviews,
        draft_repository=drafts,
        validation_service=ValidationService(),
    )
    authenticated = AuthenticatedUser(
        user_id=user.user_id,
        username=user.username,
        role=user.role,
    )
    return service, reviews, authenticated, task.task_id


def test_approval_creates_immutable_approved_version() -> None:
    service, repository, user, task_id = _build_service()
    version = service.start_review(task_id, user)
    approved = service.approve(
        version.version_id,
        user,
        reason="Verified",
        confirmed_document_type=DocumentType.INVOICE,
    )
    assert approved.status.value == "approved"
    assert approved.approved_by == user.user_id
    with pytest.raises(ApprovedVersionImmutable):
        repository.reject(approved.version_id)
    actions = repository.list_actions(version.version_id)
    assert [item.action for item in actions] == ["review_started", "approved"]


def test_blocking_arithmetic_issue_prevents_approval() -> None:
    service, repository, user, task_id = _build_service()
    version = service.start_review(task_id, user)
    payload = dict(version.document_json)
    payload["total"] = "99.00"
    edited = service.save_edit(
        version.version_id,
        payload,
        user,
        reason="Entered printed total",
    )
    with pytest.raises(UnresolvedBlockingIssues):
        service.approve(
            edited.version_id,
            user,
            reason="Checked",
            confirmed_document_type=DocumentType.INVOICE,
        )


def test_reclassify_creates_audited_new_version() -> None:
    service, repository, user, task_id = _build_service()
    version = service.start_review(task_id, user)

    reclassified = service.reclassify(
        version.version_id,
        DocumentType.RECEIVE_NOTE,
        user,
        reason="Source is a goods received note",
    )

    assert reclassified.version_number == 2
    assert reclassified.document_type == DocumentType.RECEIVE_NOTE
    assert reclassified.document_json["document_type"] == "receive_note"
    assert service.list_queue()[0]["document_type"] == "receive_note"
    actions = repository.list_actions(reclassified.version_id)
    assert [item.action for item in actions] == ["document_reclassified"]
    assert actions[0].old_value == "invoice"
    assert actions[0].new_value == "receive_note"

    with pytest.raises(ReviewConflict):
        service.approve(
            version.version_id,
            user,
            reason="Trying the obsolete version",
            confirmed_document_type=DocumentType.INVOICE,
        )


def test_approval_requires_matching_type_confirmation() -> None:
    service, _, user, task_id = _build_service()
    version = service.start_review(task_id, user)

    with pytest.raises(DocumentTypeConfirmationMismatch):
        service.approve(
            version.version_id,
            user,
            reason="Wrong confirmation",
            confirmed_document_type=DocumentType.RECEIVE_NOTE,
        )


def test_validation_preview_returns_financial_and_schema_issues() -> None:
    service, _, user, task_id = _build_service()
    version = service.start_review(task_id, user)
    mismatched = dict(version.document_json)
    mismatched["total"] = "99.00"

    financial = service.preview_validation(version.version_id, mismatched)

    assert financial["schema_valid"] is True
    assert financial["blocking_count"] == 1
    assert financial["issues"][0]["rule_code"] == "TOTAL_MISMATCH"

    invalid = dict(version.document_json)
    invalid["items"] = []
    schema = service.preview_validation(version.version_id, invalid)

    assert schema["schema_valid"] is False
    assert schema["blocking_count"] == 1
    assert schema["issues"][0]["rule_code"] == "SCHEMA_INVALID"
