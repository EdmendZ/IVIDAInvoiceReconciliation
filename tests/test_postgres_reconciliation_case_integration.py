"""Disposable real-PostgreSQL checks for Case constraints and concurrency."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import json
import os
from threading import Barrier

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import sessionmaker

from app.domain.reconciliation_cases import CaseAction, CaseActionType, CaseStatus
from app.infra.postgres_reconciliation_case_repository import (
    PostgresReconciliationCaseRepository,
)
from app.services.reconciliation_case_service import CaseError


POSTGRES_URL = os.environ.get("IVIDA_TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(
    POSTGRES_URL is None,
    reason="IVIDA_TEST_POSTGRES_URL must point to a disposable PostgreSQL database",
)
NOW = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)


@pytest.fixture()
def postgres_factory():
    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL, pool_pre_ping=True)
    with engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE case_actions, case_items, reconciliation_cases, "
                "reconciliation_line_results, reconciliations, document_versions, "
                "admin_users CASCADE"
            )
        )
        connection.execute(text("SET session_replication_role = replica"))
        connection.execute(
            text(
                "INSERT INTO admin_users "
                "(user_id, username, password_hash, role, is_active, created_at) "
                "VALUES "
                "('reviewer-1', 'alice', 'hash', 'reviewer', true, :now), "
                "('reviewer-2', 'bob', 'hash', 'reviewer', true, :now)"
            ),
            {"now": NOW},
        )
        connection.execute(
            text(
                "INSERT INTO document_versions "
                "(version_id, task_id, source_draft_id, version_number, "
                "document_type, document_json, status, created_by, created_at, "
                "source_kind, trust_method) "
                "VALUES ('invoice-version', 'task-seed', 'draft-seed', 1, "
                "'invoice', CAST(:document AS jsonb), 'approved', "
                "'reviewer-1', :now, 'invoice_upload', 'human_approved')"
            ),
            {"document": json.dumps({"invoice_number": "INV-SEED"}), "now": NOW},
        )
        connection.execute(text("SET session_replication_role = origin"))
    factory = sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        engine.dispose()


def _seed_case(factory, suffix: str) -> None:
    result = {
        "invoice_number": f"INV-{suffix}",
        "receive_note_numbers": [f"RN-{suffix}"],
        "purchase_order_match": False,
        "currency_match": True,
        "lines": [],
        "summary": {
            "total_lines": 0,
            "exact_lines": 0,
            "tolerance_lines": 0,
            "mismatch_lines": 0,
            "invoice_only_lines": 0,
            "receive_note_only_lines": 0,
            "requires_review": True,
        },
    }
    with factory.begin() as session:
        session.execute(
            text(
                "INSERT INTO reconciliations "
                "(reconciliation_id, invoice_version_id, result_json, created_by, created_at) "
                "VALUES (:reconciliation_id, 'invoice-version', CAST(:result AS jsonb), "
                "'reviewer-1', :now)"
            ),
            {
                "reconciliation_id": f"recon-{suffix}",
                "result": json.dumps(result),
                "now": NOW,
            },
        )
        session.execute(
            text(
                "INSERT INTO reconciliation_line_results "
                "(line_result_id, reconciliation_id, line_index, result_json) "
                "VALUES (:line_id, :reconciliation_id, 0, CAST(:line AS jsonb))"
            ),
            {
                "line_id": f"line-{suffix}",
                "reconciliation_id": f"recon-{suffix}",
                "line": json.dumps({"status": "mismatch"}),
            },
        )
        session.execute(
            text(
                "INSERT INTO reconciliation_cases "
                "(case_id, reconciliation_id, status, revision, created_by, created_at) "
                "VALUES (:case_id, :reconciliation_id, 'unassigned', 1, "
                "'reviewer-1', :now)"
            ),
            {
                "case_id": f"case-{suffix}",
                "reconciliation_id": f"recon-{suffix}",
                "now": NOW,
            },
        )
        session.execute(
            text(
                "INSERT INTO case_items "
                "(item_id, case_id, reconciliation_id, item_type, line_result_id, updated_at) "
                "VALUES (:item_id, :case_id, :reconciliation_id, 'line', :line_id, :now)"
            ),
            {
                "item_id": f"item-{suffix}",
                "case_id": f"case-{suffix}",
                "reconciliation_id": f"recon-{suffix}",
                "line_id": f"line-{suffix}",
                "now": NOW,
            },
        )
        session.execute(
            text(
                "INSERT INTO case_actions "
                "(action_id, case_id, actor_user_id, action, created_at) "
                "VALUES (:action_id, :case_id, 'reviewer-1', 'created', :now)"
            ),
            {"action_id": f"created-{suffix}", "case_id": f"case-{suffix}", "now": NOW},
        )


def test_postgresql_rejects_terminal_insert_and_cross_aggregate_references(
    postgres_factory,
) -> None:
    _seed_case(postgres_factory, "a")
    _seed_case(postgres_factory, "b")

    with postgres_factory() as session, pytest.raises(IntegrityError):
        session.execute(
            text(
                "INSERT INTO case_items "
                "(item_id, case_id, reconciliation_id, item_type, line_result_id, updated_at) "
                "VALUES ('cross-line', 'case-a', 'recon-a', 'line', 'line-b', :now)"
            ),
            {"now": NOW},
        )
        session.commit()

    with postgres_factory() as session, pytest.raises(IntegrityError):
        session.execute(
            text(
                "INSERT INTO case_actions "
                "(action_id, case_id, item_id, actor_user_id, action, created_at) "
                "VALUES ('cross-action', 'case-a', 'item-b', 'reviewer-1', "
                "'resolution_changed', :now)"
            ),
            {"now": NOW},
        )
        session.commit()

    with postgres_factory.begin() as session:
        session.execute(
            text("UPDATE reconciliation_cases SET status='approved' WHERE case_id='case-a'")
        )
    with postgres_factory() as session, pytest.raises(DBAPIError, match="terminal"):
        session.execute(
            text(
                "INSERT INTO case_items "
                "(item_id, case_id, reconciliation_id, item_type, updated_at) "
                "VALUES ('late-header', 'case-a', 'recon-a', "
                "'purchase_order_conflict', :now)"
            ),
            {"now": NOW},
        )
        session.commit()


def test_postgresql_concurrent_claim_has_one_winner_and_stable_loser_code(
    postgres_factory,
) -> None:
    _seed_case(postgres_factory, "claim")
    repository = PostgresReconciliationCaseRepository(postgres_factory)
    original = repository.get_bundle("case-claim")
    assert original is not None
    barrier = Barrier(2)

    def claim(user_id: str, offset: int) -> str:
        claimed_at = NOW + timedelta(seconds=offset)
        bundle = original.model_copy(
            update={
                "case": original.case.model_copy(
                    update={
                        "status": CaseStatus.IN_PROGRESS,
                        "assignee_user_id": user_id,
                        "claimed_at": claimed_at,
                    }
                )
            }
        )
        barrier.wait()
        try:
            repository.save_case_mutation(
                bundle,
                CaseAction(
                    action_id=f"claim-{user_id}",
                    case_id="case-claim",
                    actor_user_id=user_id,
                    action=CaseActionType.CLAIMED,
                    new_value=user_id,
                    created_at=claimed_at,
                ),
                expected_revision=1,
            )
            return "won"
        except CaseError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(claim, ["reviewer-1", "reviewer-2"], [1, 2])
        )

    assert sorted(results) == ["CASE_ALREADY_CLAIMED", "won"]
    stored = repository.get_bundle("case-claim")
    assert stored is not None
    assert stored.case.revision == 2
    assert stored.case.assignee_user_id in {"reviewer-1", "reviewer-2"}
    assert len([action for action in stored.actions if action.action == CaseActionType.CLAIMED]) == 1
