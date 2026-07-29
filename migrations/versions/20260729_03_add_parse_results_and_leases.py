"""Add durable extraction leases and MinerU parse results.

Revision ID: 20260729_03
Revises: 20260729_02
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260729_03"
down_revision: str | None = "20260729_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "extraction_runs",
        sa.Column("phase_error_code", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "extraction_runs",
        sa.Column("remote_job_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "extraction_runs",
        sa.Column(
            "attempt_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "extraction_runs",
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "extraction_runs",
        sa.Column("lease_owner", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "extraction_runs",
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_extraction_runs_claim",
        "extraction_runs",
        ["status", "next_attempt_at", "created_at"],
    )
    op.create_table(
        "parse_results",
        sa.Column("parse_result_id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("remote_job_id", sa.String(length=255), nullable=False),
        sa.Column("artifact_object_key", sa.String(length=1024), nullable=False),
        sa.Column("markdown", sa.Text(), nullable=False),
        sa.Column(
            "content_blocks",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("tables", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["extraction_runs.run_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("parse_result_id"),
        sa.UniqueConstraint("run_id"),
    )
    op.create_index("ix_parse_results_run_id", "parse_results", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_parse_results_run_id", table_name="parse_results")
    op.drop_table("parse_results")
    op.drop_index("ix_extraction_runs_claim", table_name="extraction_runs")
    op.drop_column("extraction_runs", "lease_expires_at")
    op.drop_column("extraction_runs", "lease_owner")
    op.drop_column("extraction_runs", "next_attempt_at")
    op.drop_column("extraction_runs", "attempt_count")
    op.drop_column("extraction_runs", "remote_job_id")
    op.drop_column("extraction_runs", "phase_error_code")
