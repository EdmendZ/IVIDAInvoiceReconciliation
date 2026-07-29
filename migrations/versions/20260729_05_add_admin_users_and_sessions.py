"""Add reviewer accounts and hashed sessions.

Revision ID: 20260729_05
Revises: 20260729_04
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260729_05"
down_revision: str | None = "20260729_04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "admin_users",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("username", sa.String(length=100), nullable=False),
        sa.Column("password_hash", sa.String(length=512), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("user_id"),
        sa.UniqueConstraint("username"),
    )
    op.create_table(
        "admin_sessions",
        sa.Column("session_token_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["admin_users.user_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("session_token_hash"),
    )
    op.create_index("ix_admin_sessions_user_id", "admin_sessions", ["user_id"])
    op.create_index(
        "ix_admin_sessions_expires_at",
        "admin_sessions",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_admin_sessions_expires_at", table_name="admin_sessions")
    op.drop_index("ix_admin_sessions_user_id", table_name="admin_sessions")
    op.drop_table("admin_sessions")
    op.drop_table("admin_users")
