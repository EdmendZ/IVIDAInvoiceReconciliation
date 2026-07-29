"""Persist reconciliation results linked to approved versions.

Revision ID: 20260729_07
Revises: 20260729_06
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260729_07"
down_revision: str | None = "20260729_06"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reconciliations",
        sa.Column("reconciliation_id", sa.String(length=36), nullable=False),
        sa.Column("invoice_version_id", sa.String(length=36), nullable=False),
        sa.Column(
            "result_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["invoice_version_id"],
            ["document_versions.version_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["admin_users.user_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("reconciliation_id"),
    )
    op.create_index(
        "ix_reconciliations_invoice_version",
        "reconciliations",
        ["invoice_version_id"],
    )
    op.create_table(
        "reconciliation_receive_notes",
        sa.Column("reconciliation_id", sa.String(length=36), nullable=False),
        sa.Column("receive_note_version_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["reconciliation_id"],
            ["reconciliations.reconciliation_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["receive_note_version_id"],
            ["document_versions.version_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "reconciliation_id",
            "receive_note_version_id",
        ),
    )
    op.create_table(
        "reconciliation_line_results",
        sa.Column("line_result_id", sa.String(length=36), nullable=False),
        sa.Column("reconciliation_id", sa.String(length=36), nullable=False),
        sa.Column("line_index", sa.Integer(), nullable=False),
        sa.Column(
            "result_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["reconciliation_id"],
            ["reconciliations.reconciliation_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("line_result_id"),
    )
    op.create_index(
        "uq_reconciliation_line_index",
        "reconciliation_line_results",
        ["reconciliation_id", "line_index"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "uq_reconciliation_line_index",
        table_name="reconciliation_line_results",
    )
    op.drop_table("reconciliation_line_results")
    op.drop_table("reconciliation_receive_notes")
    op.drop_index(
        "ix_reconciliations_invoice_version",
        table_name="reconciliations",
    )
    op.drop_table("reconciliations")
