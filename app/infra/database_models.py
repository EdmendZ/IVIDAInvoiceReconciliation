from datetime import datetime

from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Boolean,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.database import Base


class ExtractionTaskRow(Base):
    __tablename__ = "extraction_tasks"

    task_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_type: Mapped[str] = mapped_column(String(32), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_bucket: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_object_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    purchase_order_hint: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_extraction_tasks_created_at", "created_at"),
        Index("ix_extraction_tasks_sha256", "sha256"),
        Index("ix_extraction_tasks_status", "status"),
    )


class ExtractionRunRow(Base):
    __tablename__ = "extraction_runs"

    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("extraction_tasks.task_id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    raw_output: Mapped[dict | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=True,
    )
    normalized_output: Mapped[dict | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=True,
    )
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_cost_aud: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 6),
        nullable=True,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    phase_error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    remote_job_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    lease_owner: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_extraction_runs_task_id", "task_id"),
        Index("ix_extraction_runs_status", "status"),
        Index("ix_extraction_runs_created_at", "created_at"),
        Index(
            "ix_extraction_runs_claim",
            "status",
            "next_attempt_at",
            "created_at",
        ),
    )


class ParseResultRow(Base):
    __tablename__ = "parse_results"

    parse_result_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("extraction_runs.run_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    remote_job_id: Mapped[str] = mapped_column(String(255), nullable=False)
    artifact_object_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    markdown: Mapped[str] = mapped_column(Text, nullable=False)
    content_blocks: Mapped[list] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
    )
    tables: Mapped[list] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
    )
    page_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    __table_args__ = (Index("ix_parse_results_run_id", "run_id"),)


class DocumentDraftRow(Base):
    __tablename__ = "document_drafts"

    draft_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("extraction_runs.run_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    task_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("extraction_tasks.task_id", ondelete="CASCADE"),
        nullable=False,
    )
    document_type: Mapped[str] = mapped_column(String(32), nullable=False)
    normalized_json: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
    )
    validation_state: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    __table_args__ = (Index("ix_document_drafts_task_id", "task_id"),)


class FieldEvidenceRow(Base):
    __tablename__ = "field_evidence"

    evidence_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    draft_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("document_drafts.draft_id", ondelete="CASCADE"),
        nullable=False,
    )
    field_path: Mapped[str] = mapped_column(String(512), nullable=False)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    block_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    table_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    row_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence: Mapped[Decimal | None] = mapped_column(
        Numeric(6, 5),
        nullable=True,
    )

    __table_args__ = (
        Index("ix_field_evidence_draft_field", "draft_id", "field_path"),
    )


class ValidationIssueRow(Base):
    __tablename__ = "validation_issues"

    issue_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    draft_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("document_drafts.draft_id", ondelete="CASCADE"),
        nullable=False,
    )
    rule_code: Mapped[str] = mapped_column(String(100), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    field_path: Mapped[str] = mapped_column(String(512), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    measured_difference: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 6),
        nullable=True,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    __table_args__ = (
        Index(
            "ix_validation_issues_draft_severity",
            "draft_id",
            "severity",
            "resolved_at",
        ),
    )


class AdminUserRow(Base):
    __tablename__ = "admin_users"

    user_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    username: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class AdminSessionRow(Base):
    __tablename__ = "admin_sessions"

    session_token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("admin_users.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_admin_sessions_user_id", "user_id"),
        Index("ix_admin_sessions_expires_at", "expires_at"),
    )


class DocumentVersionRow(Base):
    __tablename__ = "document_versions"

    version_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("extraction_tasks.task_id", ondelete="CASCADE"),
        nullable=False,
    )
    source_draft_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("document_drafts.draft_id", ondelete="RESTRICT"),
        nullable=False,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    document_type: Mapped[str] = mapped_column(String(32), nullable=False)
    document_json: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_by: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("admin_users.user_id", ondelete="RESTRICT"),
        nullable=False,
    )
    approved_by: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("admin_users.user_id", ondelete="RESTRICT"),
        nullable=True,
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_document_versions_task_id", "task_id"),
        Index("ix_document_versions_status", "status"),
        Index(
            "uq_document_versions_task_number",
            "task_id",
            "version_number",
            unique=True,
        ),
    )


class ReviewActionRow(Base):
    __tablename__ = "review_actions"

    action_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    version_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("document_versions.version_id", ondelete="RESTRICT"),
        nullable=False,
    )
    actor_user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("admin_users.user_id", ondelete="RESTRICT"),
        nullable=False,
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    field_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    old_value: Mapped[object | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=True,
    )
    new_value: Mapped[object | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=True,
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    __table_args__ = (Index("ix_review_actions_version_id", "version_id"),)


class ReconciliationRow(Base):
    __tablename__ = "reconciliations"

    reconciliation_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    invoice_version_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("document_versions.version_id", ondelete="RESTRICT"),
        nullable=False,
    )
    result_json: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
    )
    created_by: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("admin_users.user_id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_reconciliations_invoice_version", "invoice_version_id"),
    )


class ReconciliationReceiveNoteRow(Base):
    __tablename__ = "reconciliation_receive_notes"

    reconciliation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("reconciliations.reconciliation_id", ondelete="CASCADE"),
        primary_key=True,
    )
    receive_note_version_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("document_versions.version_id", ondelete="RESTRICT"),
        primary_key=True,
    )


class ReconciliationLineResultRow(Base):
    __tablename__ = "reconciliation_line_results"

    line_result_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    reconciliation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("reconciliations.reconciliation_id", ondelete="CASCADE"),
        nullable=False,
    )
    line_index: Mapped[int] = mapped_column(Integer, nullable=False)
    result_json: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
    )

    __table_args__ = (
        Index(
            "uq_reconciliation_line_index",
            "reconciliation_id",
            "line_index",
            unique=True,
        ),
    )
