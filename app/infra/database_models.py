"""SQLAlchemy 持久化行模型。

这些 Row 只描述数据库结构；业务约束与状态语义位于 app/domain 和
app/services，Repository 负责二者转换。
"""

from datetime import datetime

from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.database import Base


class ExtractionTaskRow(Base):
    """一份上传原件的文件级元数据和当前摘要状态。"""

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


class WorkerHeartbeatRow(Base):
    """每个 Worker 的启动时间、版本与最近心跳。"""

    __tablename__ = "worker_heartbeats"

    worker_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_worker_heartbeats_last_seen_at", "last_seen_at"),
    )


class ExtractionRunRow(Base):
    """一次处理尝试的调度、租约、模型溯源、计量和终态。"""

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
    cancel_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    cancel_requested_by: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("admin_users.user_id", ondelete="RESTRICT"),
        nullable=True,
    )
    cancel_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    cancelled_stage: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    remote_may_continue: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    parser_provider: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    parser_model: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    normalizer_provider: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    normalizer_model: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    prompt_version: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    normalization_latency_ms: Mapped[int | None] = mapped_column(
        Integer,
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
    """MinerU 文本/版面结果及其 MinIO ZIP 对象键。"""

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
    """LLM 生成且尚未人工确认的规范化 JSON。"""

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
    """Draft 字段到原文页码、文本和表格位置的映射。"""

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
    """Draft 上的 Warning/Blocking 确定性规则问题。"""

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
    """后台用户与 Argon2 Password Hash。"""

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
    """浏览器 Session 的 Token Hash 和过期时间。"""

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
    """人工审核生成的不可覆盖业务快照。"""

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
    """版本上的追加式人工操作审计记录。"""

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
    """一次核对的头记录、Invoice Version 和完整结果快照。"""

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
    """一次核对参与的多个 Receive Note Versions 连接表。"""

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
    """为查询和统计单独保存的逐商品行核对结果。"""

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


class ReconciliationCaseRow(Base):
    """A reviewer-owned workflow case for one reconciliation result."""

    __tablename__ = "reconciliation_cases"

    case_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    reconciliation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("reconciliations.reconciliation_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    assignee_user_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("admin_users.user_id", ondelete="RESTRICT"),
        nullable=True,
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("admin_users.user_id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    __table_args__ = (
        Index("ix_reconciliation_cases_status", "status"),
        Index("ix_reconciliation_cases_assignee", "assignee_user_id"),
        Index(
            "ix_reconciliation_cases_created_at_case_id",
            "created_at",
            "case_id",
        ),
    )


class CaseItemRow(Base):
    """A header- or line-level exception requiring reviewer resolution."""

    __tablename__ = "case_items"

    item_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    case_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("reconciliation_cases.case_id", ondelete="CASCADE"),
        nullable=False,
    )
    item_type: Mapped[str] = mapped_column(String(32), nullable=False)
    line_result_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey(
            "reconciliation_line_results.line_result_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    resolution_type: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
    )
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("admin_users.user_id", ondelete="RESTRICT"),
        nullable=True,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "(item_type = 'line' AND line_result_id IS NOT NULL) OR "
            "(item_type <> 'line' AND line_result_id IS NULL)",
            name="ck_case_items_line_result",
        ),
        CheckConstraint(
            "resolution_type IS NULL OR "
            "(resolution_note IS NOT NULL AND "
            "length(trim(resolution_note)) > 0 AND "
            "resolved_by IS NOT NULL AND resolved_at IS NOT NULL)",
            name="ck_case_items_resolution_complete",
        ),
        Index("ix_case_items_case_id", "case_id"),
        Index(
            "uq_case_items_line_result",
            "case_id",
            "line_result_id",
            unique=True,
            postgresql_where=text("line_result_id IS NOT NULL"),
            sqlite_where=text("line_result_id IS NOT NULL"),
        ),
        Index(
            "uq_case_items_header_type",
            "case_id",
            "item_type",
            unique=True,
            postgresql_where=text("item_type <> 'line'"),
            sqlite_where=text("item_type <> 'line'"),
        ),
    )


class CaseActionRow(Base):
    """Append-only audit event for a reconciliation case or case item."""

    __tablename__ = "case_actions"

    action_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    case_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("reconciliation_cases.case_id", ondelete="CASCADE"),
        nullable=False,
    )
    item_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("case_items.item_id", ondelete="RESTRICT"),
        nullable=True,
    )
    actor_user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("admin_users.user_id", ondelete="RESTRICT"),
        nullable=False,
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
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

    __table_args__ = (
        Index(
            "ix_case_actions_case_created_action",
            "case_id",
            "created_at",
            "action_id",
        ),
    )
