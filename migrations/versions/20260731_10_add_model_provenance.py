"""Add parser, normalizer and prompt provenance.

Revision ID: 20260731_10
Revises: 20260731_09
Create Date: 2026-07-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260731_10"
down_revision: str | None = "20260731_09"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for name in (
        "parser_provider",
        "parser_model",
        "normalizer_provider",
        "normalizer_model",
        "prompt_version",
    ):
        op.add_column(
            "extraction_runs",
            sa.Column(name, sa.String(length=255), nullable=True),
        )
    op.add_column(
        "extraction_runs",
        sa.Column("normalization_latency_ms", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("extraction_runs", "normalization_latency_ms")
    op.drop_column("extraction_runs", "prompt_version")
    op.drop_column("extraction_runs", "normalizer_model")
    op.drop_column("extraction_runs", "normalizer_provider")
    op.drop_column("extraction_runs", "parser_model")
    op.drop_column("extraction_runs", "parser_provider")
