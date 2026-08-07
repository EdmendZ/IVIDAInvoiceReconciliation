"""Add extraction quality experiment persistence.

Revision ID: 20260807_12
Revises: 20260803_11
Create Date: 2026-08-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260807_12"
down_revision: str | None = "20260803_11"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "experiment_definitions",
        sa.Column("experiment_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("manifest_path", sa.String(length=1024), nullable=False),
        sa.Column("dataset_identity", postgresql.JSONB(), nullable=False),
        sa.Column("parser_provider", sa.String(length=255), nullable=False),
        sa.Column("parser_model", sa.String(length=255), nullable=False),
        sa.Column("parser_version", sa.String(length=255), nullable=False),
        sa.Column("normalizer_provider", sa.String(length=255), nullable=False),
        sa.Column("normalizer_model", sa.String(length=255), nullable=False),
        sa.Column("prompt_version", sa.String(length=255), nullable=False),
        sa.Column("schema_version", sa.String(length=255), nullable=False),
        sa.Column("parameters", postgresql.JSONB(), nullable=False),
        sa.Column("thresholds", postgresql.JSONB(), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "role IN ('baseline', 'candidate')",
            name="ck_experiment_definitions_role",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["admin_users.user_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("experiment_id"),
    )

    op.create_table(
        "evaluation_runs",
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("experiment_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("summary", postgresql.JSONB(), nullable=True),
        sa.Column("documents", postgresql.JSONB(), nullable=False),
        sa.Column("slices", postgresql.JSONB(), nullable=False),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed', 'cancelled')",
            name="ck_evaluation_runs_status",
        ),
        sa.ForeignKeyConstraint(
            ["experiment_id"],
            ["experiment_definitions.experiment_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("run_id"),
    )
    op.create_index(
        "ix_evaluation_runs_experiment_created",
        "evaluation_runs",
        ["experiment_id", "created_at"],
    )
    op.create_index(
        "ix_evaluation_runs_status",
        "evaluation_runs",
        ["status"],
    )

    op.create_table(
        "feedback_candidates",
        sa.Column("candidate_id", sa.String(length=36), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("classification", sa.String(length=64), nullable=True),
        sa.Column("include_in_gold", sa.Boolean(), nullable=False),
        sa.Column("confirmed_by", sa.String(length=36), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "classification IS NULL OR classification IN "
            "('model_error', 'acceptable_variant', "
            "'reviewer_correction_error', 'business_context_update')",
            name="ck_feedback_candidates_classification",
        ),
        sa.ForeignKeyConstraint(
            ["confirmed_by"],
            ["admin_users.user_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("candidate_id"),
    )
    op.create_index(
        "ix_feedback_candidates_confirmation",
        "feedback_candidates",
        ["confirmed_at", "created_at"],
    )

    op.create_table(
        "promotion_decisions",
        sa.Column("decision_id", sa.String(length=36), nullable=False),
        sa.Column("baseline_run_id", sa.String(length=36), nullable=False),
        sa.Column("candidate_run_id", sa.String(length=36), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("decided_by", sa.String(length=36), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "outcome IN ('recommended', 'rejected', 'inconclusive')",
            name="ck_promotion_decisions_outcome",
        ),
        sa.ForeignKeyConstraint(
            ["baseline_run_id"],
            ["evaluation_runs.run_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_run_id"],
            ["evaluation_runs.run_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["decided_by"],
            ["admin_users.user_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("decision_id"),
    )
    op.create_index(
        "ix_promotion_decisions_candidate",
        "promotion_decisions",
        ["candidate_run_id", "decided_at"],
    )

    op.execute(
        """
        CREATE FUNCTION reject_experiment_definition_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'experiment definitions are immutable';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_experiment_definitions_immutable
        BEFORE UPDATE OR DELETE ON experiment_definitions
        FOR EACH ROW EXECUTE FUNCTION reject_experiment_definition_mutation()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_experiment_definitions_immutable "
        "ON experiment_definitions"
    )
    op.execute("DROP FUNCTION IF EXISTS reject_experiment_definition_mutation()")
    op.drop_index(
        "ix_promotion_decisions_candidate",
        table_name="promotion_decisions",
    )
    op.drop_table("promotion_decisions")
    op.drop_index(
        "ix_feedback_candidates_confirmation",
        table_name="feedback_candidates",
    )
    op.drop_table("feedback_candidates")
    op.drop_index("ix_evaluation_runs_status", table_name="evaluation_runs")
    op.drop_index(
        "ix_evaluation_runs_experiment_created",
        table_name="evaluation_runs",
    )
    op.drop_table("evaluation_runs")
    op.drop_table("experiment_definitions")
