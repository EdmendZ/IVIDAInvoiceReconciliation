from datetime import UTC, datetime, timedelta
from io import StringIO

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import CheckConstraint, create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domain.reconciliation import ReconciliationResult, ReconciliationSummary
from app.domain.reconciliation_cases import (
    AssignmentFilter,
    CaseAction,
    CaseActionType,
    CaseItem,
    CaseItemType,
    CaseListQuery,
    CaseStatus,
    ReconciliationCase,
    ReconciliationCaseBundle,
    ResolutionType,
)
from app.domain.reconciliation_records import (
    ReconciliationPersistenceBundle,
    ReconciliationRecord,
)
from app.infra.database import Base
from app.infra.database_models import (
    AdminUserRow,
    CaseActionRow,
    CaseItemRow,
    ReconciliationCaseRow,
)
from app.infra.postgres_reconciliation_case_repository import (
    PostgresReconciliationCaseRepository,
)
from app.infra.postgres_reconciliation_repository import (
    PostgresReconciliationRepository,
)
from app.services.reconciliation_case_service import CaseError


NOW = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)


def _factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as session:
        session.add_all(
            [
                AdminUserRow(
                    user_id="reviewer-1",
                    username="alice",
                    password_hash="hash",
                    role="reviewer",
                    is_active=True,
                    created_at=NOW,
                ),
                AdminUserRow(
                    user_id="reviewer-2",
                    username="bob",
                    password_hash="hash",
                    role="reviewer",
                    is_active=True,
                    created_at=NOW,
                ),
            ]
        )
        session.commit()
    return factory


def _persistence_bundle(
    *,
    reconciliation_id: str,
    case_id: str,
    invoice_number: str,
    created_at: datetime,
    assignee_user_id: str | None = None,
    status: CaseStatus = CaseStatus.UNASSIGNED,
) -> ReconciliationPersistenceBundle:
    record = ReconciliationRecord(
        reconciliation_id=reconciliation_id,
        invoice_version_id=f"invoice-{reconciliation_id}",
        receive_note_version_ids=[f"note-{reconciliation_id}"],
        result=ReconciliationResult(
            invoice_number=invoice_number,
            receive_note_numbers=[f"RN-{reconciliation_id}"],
            purchase_order_match=False,
            currency_match=True,
            lines=[],
            summary=ReconciliationSummary(
                total_lines=0,
                exact_lines=0,
                tolerance_lines=0,
                mismatch_lines=0,
                invoice_only_lines=0,
                receive_note_only_lines=0,
                requires_review=True,
            ),
        ),
        created_by="reviewer-1",
        created_at=created_at,
    )
    case = ReconciliationCase(
        case_id=case_id,
        reconciliation_id=reconciliation_id,
        status=status,
        assignee_user_id=assignee_user_id,
        revision=1,
        created_by="reviewer-1",
        created_at=created_at,
    )
    case_bundle = ReconciliationCaseBundle(
        case=case,
        items=[
            CaseItem(
                item_id=f"item-{case_id}",
                case_id=case_id,
                item_type=CaseItemType.PURCHASE_ORDER_CONFLICT,
                updated_at=created_at,
            )
        ],
        actions=[
            CaseAction(
                action_id=f"created-{case_id}",
                case_id=case_id,
                actor_user_id="reviewer-1",
                action=CaseActionType.CREATED,
                created_at=created_at,
            )
        ],
    )
    return ReconciliationPersistenceBundle(
        record=record,
        line_result_ids=[],
        case=case_bundle,
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


def test_terminal_item_trigger_locks_parent_cases_in_stable_order() -> None:
    output = StringIO()
    config = Config("alembic.ini", output_buffer=output)
    config.set_main_option("path_separator", "os")

    command.upgrade(config, "head", sql=True)

    sql = output.getvalue()
    function_start = sql.index(
        "CREATE FUNCTION reject_terminal_case_item_mutation()"
    )
    function_end = sql.index(
        "CREATE TRIGGER trg_case_items_terminal_immutable",
        function_start,
    )
    trigger_function_sql = " ".join(
        sql[function_start:function_end].lower().split()
    )
    assert (
        "where case_id in (old.case_id, new.case_id) "
        "order by case_id for update"
    ) in trigger_function_sql
    assert "where case_id = old.case_id for update" in trigger_function_sql


def test_get_bundle_and_detail_return_stable_action_order_and_actor_names() -> None:
    factory = _factory()
    persistence = _persistence_bundle(
        reconciliation_id="recon-1",
        case_id="case-1",
        invoice_number="INV-001",
        created_at=NOW,
    )
    PostgresReconciliationRepository(factory).create(persistence)
    with factory() as session:
        session.add_all(
            [
                CaseActionRow(
                    action_id="action-z",
                    case_id="case-1",
                    actor_user_id="reviewer-2",
                    action=CaseActionType.REASSIGNED.value,
                    old_value="reviewer-1",
                    new_value="reviewer-2",
                    reason="coverage",
                    created_at=NOW + timedelta(minutes=1),
                ),
                CaseActionRow(
                    action_id="action-a",
                    case_id="case-1",
                    actor_user_id="reviewer-1",
                    action=CaseActionType.CLAIMED.value,
                    old_value=None,
                    new_value="reviewer-1",
                    created_at=NOW + timedelta(minutes=1),
                ),
            ]
        )
        session.commit()

    repository = PostgresReconciliationCaseRepository(factory)
    bundle = repository.get_bundle("case-1")
    by_reconciliation = repository.get_by_reconciliation("recon-1")
    detail = repository.get_detail("case-1")

    assert bundle is not None
    assert by_reconciliation == bundle
    assert [action.action_id for action in bundle.actions] == [
        "created-case-1",
        "action-a",
        "action-z",
    ]
    assert detail is not None
    assert detail.reconciliation == persistence.record
    assert [view.actor_username for view in detail.actions] == [
        "alice",
        "alice",
        "bob",
    ]


def test_save_case_mutation_updates_one_item_and_rejects_stale_revision() -> None:
    factory = _factory()
    persistence = _persistence_bundle(
        reconciliation_id="recon-1",
        case_id="case-1",
        invoice_number="INV-001",
        created_at=NOW,
    )
    PostgresReconciliationRepository(factory).create(persistence)
    repository = PostgresReconciliationCaseRepository(factory)
    original = repository.get_bundle("case-1")
    assert original is not None
    claimed_case = original.case.model_copy(
        update={
            "status": CaseStatus.IN_PROGRESS,
            "assignee_user_id": "reviewer-1",
            "claimed_at": NOW + timedelta(minutes=1),
        }
    )
    claim_action = CaseAction(
        action_id="action-claim",
        case_id="case-1",
        actor_user_id="reviewer-1",
        action=CaseActionType.CLAIMED,
        new_value="reviewer-1",
        created_at=NOW + timedelta(minutes=1),
    )

    claimed = repository.save_case_mutation(
        original.model_copy(update={"case": claimed_case}),
        claim_action,
        expected_revision=1,
    )
    resolved_at = NOW + timedelta(minutes=2)
    resolved_item = claimed.items[0].model_copy(
        update={
            "resolution_type": ResolutionType.BUSINESS_EXCEPTION,
            "resolution_note": "accepted variance",
            "resolved_by": "reviewer-1",
            "resolved_at": resolved_at,
            "updated_at": resolved_at,
        }
    )
    resolution_action = CaseAction(
        action_id="action-resolution",
        case_id="case-1",
        item_id=resolved_item.item_id,
        actor_user_id="reviewer-1",
        action=CaseActionType.RESOLUTION_CHANGED,
        new_value={"resolution_type": ResolutionType.BUSINESS_EXCEPTION},
        created_at=resolved_at,
    )
    resolved = repository.save_case_mutation(
        claimed.model_copy(update={"items": [resolved_item]}),
        resolution_action,
        expected_revision=2,
    )

    assert claimed.case.revision == 2
    assert resolved.case.revision == 3
    assert resolved.items[0].resolution_note == "accepted variance"
    assert [action.action_id for action in resolved.actions] == [
        "created-case-1",
        "action-claim",
        "action-resolution",
    ]

    with pytest.raises(CaseError) as captured:
        repository.save_case_mutation(
            claimed,
            CaseAction(
                action_id="stale-action",
                case_id="case-1",
                actor_user_id="reviewer-1",
                action=CaseActionType.SUBMITTED_FOR_APPROVAL,
                created_at=NOW + timedelta(minutes=3),
            ),
            expected_revision=2,
        )

    assert captured.value.code == "CASE_REVISION_CONFLICT"
    stored = repository.get_bundle("case-1")
    assert stored is not None
    assert stored.case.revision == 3
    assert [action.action_id for action in stored.actions] == [
        "created-case-1",
        "action-claim",
        "action-resolution",
    ]


def test_list_cases_filters_paginates_and_orders_deterministically() -> None:
    factory = _factory()
    writer = PostgresReconciliationRepository(factory)
    writer.create(
        _persistence_bundle(
            reconciliation_id="recon-2",
            case_id="case-b",
            invoice_number="INV-002",
            created_at=NOW,
            assignee_user_id="reviewer-2",
            status=CaseStatus.IN_PROGRESS,
        )
    )
    writer.create(
        _persistence_bundle(
            reconciliation_id="recon-1",
            case_id="case-a",
            invoice_number="INV-001",
            created_at=NOW,
            assignee_user_id="reviewer-1",
            status=CaseStatus.IN_PROGRESS,
        )
    )
    writer.create(
        _persistence_bundle(
            reconciliation_id="recon-0",
            case_id="case-z",
            invoice_number="OTHER-001",
            created_at=NOW - timedelta(minutes=1),
        )
    )
    repository = PostgresReconciliationCaseRepository(factory)

    first_page = repository.list_cases(
        CaseListQuery(page=1, page_size=2),
        "reviewer-1",
    )
    mine = repository.list_cases(
        CaseListQuery(
            statuses=(CaseStatus.IN_PROGRESS,),
            assignment=AssignmentFilter.MINE,
            invoice_number="INV-",
        ),
        "reviewer-1",
    )

    assert first_page.total == 3
    assert [item.case.case_id for item in first_page.items] == ["case-z", "case-a"]
    assert [item.case.case_id for item in mine.items] == ["case-a"]
    assert mine.items[0].assignee_username == "alice"
    assert mine.items[0].actionable_count == 1
