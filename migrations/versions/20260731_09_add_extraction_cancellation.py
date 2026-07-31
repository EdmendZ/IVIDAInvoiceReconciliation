"""Add cooperative extraction cancellation.

Revision ID: 20260731_09
Revises: 20260731_08
Create Date: 2026-07-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260731_09"
down_revision: str | None = "20260731_08"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "extraction_runs",
        sa.Column(
            "cancel_requested_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "extraction_runs",
        sa.Column(
            "cancel_requested_by",
            sa.String(length=36),
            nullable=True,
        ),
    )
    op.add_column(
        "extraction_runs",
        sa.Column(
            "cancel_completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "extraction_runs",
        sa.Column("cancelled_stage", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "extraction_runs",
        sa.Column(
            "remote_may_continue",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.create_foreign_key(
        "fk_extraction_runs_cancel_requested_by",
        "extraction_runs",
        "admin_users",
        ["cancel_requested_by"],
        ["user_id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_extraction_runs_cancel_requested_by",
        "extraction_runs",
        type_="foreignkey",
    )
    op.drop_column("extraction_runs", "remote_may_continue")
    op.drop_column("extraction_runs", "cancelled_stage")
    op.drop_column("extraction_runs", "cancel_completed_at")
    op.drop_column("extraction_runs", "cancel_requested_by")
    op.drop_column("extraction_runs", "cancel_requested_at")
