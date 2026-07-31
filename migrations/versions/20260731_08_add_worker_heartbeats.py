"""Add durable extraction worker heartbeats.

Revision ID: 20260731_08
Revises: 20260729_07
Create Date: 2026-07-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260731_08"
down_revision: str | None = "20260729_07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "worker_heartbeats",
        sa.Column("worker_id", sa.String(length=255), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("worker_id"),
    )
    op.create_index(
        "ix_worker_heartbeats_last_seen_at",
        "worker_heartbeats",
        ["last_seen_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_worker_heartbeats_last_seen_at",
        table_name="worker_heartbeats",
    )
    op.drop_table("worker_heartbeats")
