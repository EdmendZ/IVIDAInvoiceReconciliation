from datetime import UTC, datetime

import pytest
from sqlalchemy import CheckConstraint, create_engine
from sqlalchemy.exc import IntegrityError

from app.infra.database import Base
from app.infra.database_models import (
    CaseActionRow,
    CaseItemRow,
    ReconciliationCaseRow,
)


def test_case_schema_has_unique_reconciliation_and_revision() -> None:
    assert ReconciliationCaseRow.__table__.c.reconciliation_id.unique is True
    assert ReconciliationCaseRow.__table__.c.revision.nullable is False
    assert CaseActionRow.__table__.c.old_value.nullable is True
    assert CaseActionRow.__table__.c.new_value.nullable is True


def test_case_schema_has_required_indexes_and_item_constraints() -> None:
    case_indexes = {index.name: index for index in ReconciliationCaseRow.__table__.indexes}
    item_indexes = {index.name: index for index in CaseItemRow.__table__.indexes}
    action_indexes = {index.name: index for index in CaseActionRow.__table__.indexes}

    assert set(case_indexes) == {
        "ix_reconciliation_cases_status",
        "ix_reconciliation_cases_assignee",
        "ix_reconciliation_cases_created_at_case_id",
    }
    assert [column.name for column in case_indexes[
        "ix_reconciliation_cases_created_at_case_id"
    ].columns] == ["created_at", "case_id"]
    assert item_indexes["uq_case_items_line_result"].unique is True
    assert item_indexes["uq_case_items_header_type"].unique is True
    assert item_indexes["uq_case_items_line_result"].dialect_options[
        "sqlite"
    ]["where"] is not None
    assert item_indexes["uq_case_items_header_type"].dialect_options[
        "postgresql"
    ]["where"] is not None
    assert [column.name for column in action_indexes[
        "ix_case_actions_case_created_action"
    ].columns] == ["case_id", "created_at", "action_id"]

    checks = {
        constraint.name
        for constraint in CaseItemRow.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert checks == {
        "ck_case_items_line_result",
        "ck_case_items_resolution_complete",
    }


def test_case_orm_metadata_creates_on_sqlite() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")

    Base.metadata.create_all(engine)

    assert set(Base.metadata.tables).issuperset(
        {"reconciliation_cases", "case_items", "case_actions"}
    )


@pytest.mark.parametrize("resolution_note", [None, "  "])
def test_resolved_item_requires_a_non_blank_note_on_sqlite(
    resolution_note: str | None,
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with engine.begin() as connection, pytest.raises(IntegrityError):
        connection.execute(
            CaseItemRow.__table__.insert().values(
                item_id="item-1",
                case_id="case-1",
                item_type="purchase_order_conflict",
                resolution_type="business_exception",
                resolution_note=resolution_note,
                resolved_by="reviewer-1",
                resolved_at=datetime(2026, 8, 3, tzinfo=UTC),
                updated_at=datetime(2026, 8, 3, tzinfo=UTC),
            )
        )
