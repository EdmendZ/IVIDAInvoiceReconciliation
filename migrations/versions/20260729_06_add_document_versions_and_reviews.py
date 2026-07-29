"""Add immutable document versions and append-only review audit.

Revision ID: 20260729_06
Revises: 20260729_05
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260729_06"
down_revision: str | None = "20260729_05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "document_versions",
        sa.Column("version_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("source_draft_id", sa.String(length=36), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("document_type", sa.String(length=32), nullable=False),
        sa.Column(
            "document_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("approved_by", sa.String(length=36), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["extraction_tasks.task_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_draft_id"],
            ["document_drafts.draft_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["admin_users.user_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["approved_by"],
            ["admin_users.user_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("version_id"),
    )
    op.create_index(
        "ix_document_versions_task_id",
        "document_versions",
        ["task_id"],
    )
    op.create_index(
        "ix_document_versions_status",
        "document_versions",
        ["status"],
    )
    op.create_index(
        "uq_document_versions_task_number",
        "document_versions",
        ["task_id", "version_number"],
        unique=True,
    )
    op.create_table(
        "review_actions",
        sa.Column("action_id", sa.String(length=36), nullable=False),
        sa.Column("version_id", sa.String(length=36), nullable=False),
        sa.Column("actor_user_id", sa.String(length=36), nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("field_path", sa.String(length=512), nullable=True),
        sa.Column(
            "old_value",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "new_value",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["document_versions.version_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["admin_users.user_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("action_id"),
    )
    op.create_index(
        "ix_review_actions_version_id",
        "review_actions",
        ["version_id"],
    )
    op.execute(
        """
        CREATE FUNCTION protect_review_records() RETURNS trigger AS $$
        BEGIN
          IF TG_TABLE_NAME = 'review_actions' THEN
            RAISE EXCEPTION 'review actions are append-only';
          END IF;
          IF OLD.status = 'approved' THEN
            RAISE EXCEPTION 'approved document versions are immutable';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER protect_approved_document_versions
        BEFORE UPDATE OR DELETE ON document_versions
        FOR EACH ROW EXECUTE FUNCTION protect_review_records();
        """
    )
    op.execute(
        """
        CREATE TRIGGER protect_review_actions
        BEFORE UPDATE OR DELETE ON review_actions
        FOR EACH ROW EXECUTE FUNCTION protect_review_records();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS protect_review_actions ON review_actions")
    op.execute(
        "DROP TRIGGER IF EXISTS protect_approved_document_versions "
        "ON document_versions"
    )
    op.execute("DROP FUNCTION IF EXISTS protect_review_records()")
    op.drop_index("ix_review_actions_version_id", table_name="review_actions")
    op.drop_table("review_actions")
    op.drop_index(
        "uq_document_versions_task_number",
        table_name="document_versions",
    )
    op.drop_index("ix_document_versions_status", table_name="document_versions")
    op.drop_index("ix_document_versions_task_id", table_name="document_versions")
    op.drop_table("document_versions")
