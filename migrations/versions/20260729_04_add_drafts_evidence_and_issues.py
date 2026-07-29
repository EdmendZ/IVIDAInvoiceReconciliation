"""Add normalized drafts, field evidence and validation issues.

Revision ID: 20260729_04
Revises: 20260729_03
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260729_04"
down_revision: str | None = "20260729_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "document_drafts",
        sa.Column("draft_id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("document_type", sa.String(length=32), nullable=False),
        sa.Column(
            "normalized_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("validation_state", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["extraction_runs.run_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["extraction_tasks.task_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("draft_id"),
        sa.UniqueConstraint("run_id"),
    )
    op.create_index(
        "ix_document_drafts_task_id",
        "document_drafts",
        ["task_id"],
    )
    op.create_table(
        "field_evidence",
        sa.Column("evidence_id", sa.String(length=36), nullable=False),
        sa.Column("draft_id", sa.String(length=36), nullable=False),
        sa.Column("field_path", sa.String(length=512), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("block_id", sa.String(length=255), nullable=True),
        sa.Column("table_id", sa.String(length=255), nullable=True),
        sa.Column("row_index", sa.Integer(), nullable=True),
        sa.Column("confidence", sa.Numeric(6, 5), nullable=True),
        sa.ForeignKeyConstraint(
            ["draft_id"],
            ["document_drafts.draft_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("evidence_id"),
    )
    op.create_index(
        "ix_field_evidence_draft_field",
        "field_evidence",
        ["draft_id", "field_path"],
    )
    op.create_table(
        "validation_issues",
        sa.Column("issue_id", sa.String(length=36), nullable=False),
        sa.Column("draft_id", sa.String(length=36), nullable=False),
        sa.Column("rule_code", sa.String(length=100), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("field_path", sa.String(length=512), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("measured_difference", sa.Numeric(18, 6), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["draft_id"],
            ["document_drafts.draft_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("issue_id"),
    )
    op.create_index(
        "ix_validation_issues_draft_severity",
        "validation_issues",
        ["draft_id", "severity", "resolved_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_validation_issues_draft_severity",
        table_name="validation_issues",
    )
    op.drop_table("validation_issues")
    op.drop_index(
        "ix_field_evidence_draft_field",
        table_name="field_evidence",
    )
    op.drop_table("field_evidence")
    op.drop_index("ix_document_drafts_task_id", table_name="document_drafts")
    op.drop_table("document_drafts")
