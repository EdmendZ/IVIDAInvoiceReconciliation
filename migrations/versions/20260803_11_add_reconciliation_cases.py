"""Add reconciliation case workflow tables and immutability guards.

Revision ID: 20260803_11
Revises: 20260731_10
Create Date: 2026-08-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260803_11"
down_revision: str | None = "20260731_10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reconciliation_cases",
        sa.Column("case_id", sa.String(length=36), nullable=False),
        sa.Column("reconciliation_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("assignee_user_id", sa.String(length=36), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('unassigned', 'in_progress', 'pending_approval', "
            "'pending_void', 'approved', 'voided')",
            name="ck_reconciliation_cases_status",
        ),
        sa.CheckConstraint(
            "revision >= 1",
            name="ck_reconciliation_cases_revision",
        ),
        sa.ForeignKeyConstraint(
            ["reconciliation_id"],
            ["reconciliations.reconciliation_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["assignee_user_id"],
            ["admin_users.user_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["admin_users.user_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("case_id"),
        sa.UniqueConstraint(
            "reconciliation_id",
            name="uq_reconciliation_cases_reconciliation_id",
        ),
    )
    op.create_index(
        "ix_reconciliation_cases_status",
        "reconciliation_cases",
        ["status"],
    )
    op.create_index(
        "ix_reconciliation_cases_assignee",
        "reconciliation_cases",
        ["assignee_user_id"],
    )
    op.create_index(
        "ix_reconciliation_cases_created_at_case_id",
        "reconciliation_cases",
        ["created_at", "case_id"],
    )

    op.create_table(
        "case_items",
        sa.Column("item_id", sa.String(length=36), nullable=False),
        sa.Column("case_id", sa.String(length=36), nullable=False),
        sa.Column("item_type", sa.String(length=32), nullable=False),
        sa.Column("line_result_id", sa.String(length=36), nullable=True),
        sa.Column("resolution_type", sa.String(length=32), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("resolved_by", sa.String(length=36), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "item_type IN "
            "('line', 'purchase_order_conflict', 'currency_conflict')",
            name="ck_case_items_item_type",
        ),
        sa.CheckConstraint(
            "resolution_type IS NULL OR resolution_type IN "
            "('business_exception', 'document_data_error', "
            "'matching_error', 'waiting_for_documents')",
            name="ck_case_items_resolution_type",
        ),
        sa.CheckConstraint(
            "(item_type = 'line' AND line_result_id IS NOT NULL) OR "
            "(item_type <> 'line' AND line_result_id IS NULL)",
            name="ck_case_items_line_result",
        ),
        sa.CheckConstraint(
            "resolution_type IS NULL OR "
            "(resolution_note IS NOT NULL AND "
            "length(trim(resolution_note)) > 0 AND "
            "resolved_by IS NOT NULL AND resolved_at IS NOT NULL)",
            name="ck_case_items_resolution_complete",
        ),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["reconciliation_cases.case_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["line_result_id"],
            ["reconciliation_line_results.line_result_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["resolved_by"],
            ["admin_users.user_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("item_id"),
    )
    op.create_index("ix_case_items_case_id", "case_items", ["case_id"])
    op.create_index(
        "uq_case_items_line_result",
        "case_items",
        ["case_id", "line_result_id"],
        unique=True,
        postgresql_where=sa.text("line_result_id IS NOT NULL"),
    )
    op.create_index(
        "uq_case_items_header_type",
        "case_items",
        ["case_id", "item_type"],
        unique=True,
        postgresql_where=sa.text("item_type <> 'line'"),
    )

    op.create_table(
        "case_actions",
        sa.Column("action_id", sa.String(length=36), nullable=False),
        sa.Column("case_id", sa.String(length=36), nullable=False),
        sa.Column("item_id", sa.String(length=36), nullable=True),
        sa.Column("actor_user_id", sa.String(length=36), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
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
        sa.CheckConstraint(
            "action IN ('created', 'claimed', 'reassigned', "
            "'resolution_changed', 'submitted_for_approval', "
            "'submitted_for_void', 'returned', 'approved', 'voided')",
            name="ck_case_actions_action",
        ),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["reconciliation_cases.case_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["item_id"],
            ["case_items.item_id"],
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
        "ix_case_actions_case_created_action",
        "case_actions",
        ["case_id", "created_at", "action_id"],
    )

    op.execute(
        """
        CREATE FUNCTION reject_case_action_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'case_actions rows are append-only';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_case_actions_immutable
        BEFORE UPDATE OR DELETE ON case_actions
        FOR EACH ROW EXECUTE FUNCTION reject_case_action_mutation()
        """
    )
    op.execute(
        """
        CREATE FUNCTION reject_terminal_case_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF OLD.status IN ('approved', 'voided') THEN
                RAISE EXCEPTION 'terminal reconciliation cases are immutable';
            END IF;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_reconciliation_cases_terminal_immutable
        BEFORE UPDATE OR DELETE ON reconciliation_cases
        FOR EACH ROW EXECUTE FUNCTION reject_terminal_case_mutation()
        """
    )
    op.execute(
        """
        CREATE FUNCTION reject_terminal_case_item_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            parent_status text;
            new_parent_status text;
        BEGIN
            SELECT status INTO parent_status
            FROM reconciliation_cases
            WHERE case_id = OLD.case_id;

            IF parent_status IN ('approved', 'voided') THEN
                RAISE EXCEPTION 'items of terminal reconciliation cases are immutable';
            END IF;
            IF TG_OP = 'UPDATE' AND NEW.case_id <> OLD.case_id THEN
                SELECT status INTO new_parent_status
                FROM reconciliation_cases
                WHERE case_id = NEW.case_id;

                IF new_parent_status IN ('approved', 'voided') THEN
                    RAISE EXCEPTION 'items of terminal reconciliation cases are immutable';
                END IF;
            END IF;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_case_items_terminal_immutable
        BEFORE UPDATE OR DELETE ON case_items
        FOR EACH ROW EXECUTE FUNCTION reject_terminal_case_item_mutation()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_case_items_terminal_immutable ON case_items"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS "
        "trg_reconciliation_cases_terminal_immutable ON reconciliation_cases"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_case_actions_immutable ON case_actions"
    )
    op.execute("DROP FUNCTION IF EXISTS reject_terminal_case_item_mutation()")
    op.execute("DROP FUNCTION IF EXISTS reject_terminal_case_mutation()")
    op.execute("DROP FUNCTION IF EXISTS reject_case_action_mutation()")

    op.drop_index(
        "ix_case_actions_case_created_action",
        table_name="case_actions",
    )
    op.drop_table("case_actions")
    op.drop_index("uq_case_items_header_type", table_name="case_items")
    op.drop_index("uq_case_items_line_result", table_name="case_items")
    op.drop_index("ix_case_items_case_id", table_name="case_items")
    op.drop_table("case_items")
    op.drop_index(
        "ix_reconciliation_cases_created_at_case_id",
        table_name="reconciliation_cases",
    )
    op.drop_index(
        "ix_reconciliation_cases_assignee",
        table_name="reconciliation_cases",
    )
    op.drop_index(
        "ix_reconciliation_cases_status",
        table_name="reconciliation_cases",
    )
    op.drop_table("reconciliation_cases")
