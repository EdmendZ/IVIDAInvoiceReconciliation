"""Create extraction task table.

Revision ID: 20260729_01
Revises:
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260729_01"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "extraction_tasks",
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("document_type", sa.String(length=32), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_bucket", sa.String(length=255), nullable=False),
        sa.Column("storage_object_key", sa.String(length=1024), nullable=False),
        sa.Column("purchase_order_hint", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("task_id"),
    )
    op.create_index(
        "ix_extraction_tasks_created_at",
        "extraction_tasks",
        ["created_at"],
    )
    op.create_index(
        "ix_extraction_tasks_sha256",
        "extraction_tasks",
        ["sha256"],
    )
    op.create_index(
        "ix_extraction_tasks_status",
        "extraction_tasks",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_extraction_tasks_status", table_name="extraction_tasks")
    op.drop_index("ix_extraction_tasks_sha256", table_name="extraction_tasks")
    op.drop_index("ix_extraction_tasks_created_at", table_name="extraction_tasks")
    op.drop_table("extraction_tasks")

