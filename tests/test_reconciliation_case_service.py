from datetime import UTC, datetime

import pytest

from app.domain.admin_users import AdminRole, AuthenticatedUser
from app.domain.reconciliation_cases import (
    CaseAction,
    CaseActionType,
    CaseItem,
    CaseItemType,
    CaseListQuery,
    CasePage,
    CaseStatus,
    ReconciliationCase,
    ReconciliationCaseBundle,
    ResolutionType,
)
from app.services.reconciliation_case_service import CaseError, ReconciliationCaseService


CASE_ID = "case-1"
ITEM_IDS = ("item-1", "item-2")
NOW = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)


class FakeCaseRepository:
    def __init__(self, bundle: ReconciliationCaseBundle) -> None:
        self.bundle = bundle
        self.actions = list(bundle.actions)
        self.save_calls = 0

    def get_bundle(self, case_id: str) -> ReconciliationCaseBundle | None:
        return self.bundle if case_id == self.bundle.case.case_id else None

    def list_cases(self, query: CaseListQuery, user_id: str) -> CasePage:
        del query, user_id
        return CasePage(items=[], page=1, page_size=50, total=0)

    def save_case_mutation(
        self,
        bundle: ReconciliationCaseBundle,
        action: CaseAction,
        *,
        expected_revision: int,
    ) -> ReconciliationCaseBundle:
        self.save_calls += 1
        assert expected_revision == self.bundle.case.revision
        self.actions.append(action)
        self.bundle = bundle.model_copy(
            update={
                "case": bundle.case.model_copy(
                    update={"revision": expected_revision + 1}
                ),
                "actions": [*self.actions],
            }
        )
        return self.bundle


class FakeActiveReviewerReader:
    def __init__(self, active_reviewer_ids: set[str]) -> None:
        self.active_reviewer_ids = active_reviewer_ids

    def is_active_reviewer(self, user_id: str) -> bool:
        return user_id in self.active_reviewer_ids


def reviewer(user_id: str = "reviewer-a") -> AuthenticatedUser:
    return AuthenticatedUser(
        user_id=user_id,
        username=user_id,
        role=AdminRole.REVIEWER,
    )


def admin() -> AuthenticatedUser:
    return AuthenticatedUser(
        user_id="admin-a",
        username="admin-a",
        role=AdminRole.ADMIN,
    )


def case_bundle(
    *,
    status: CaseStatus = CaseStatus.IN_PROGRESS,
    assignee_id: str | None = "reviewer-a",
    resolution: ResolutionType | None = None,
    revision: int = 4,
) -> ReconciliationCaseBundle:
    return ReconciliationCaseBundle(
        case=ReconciliationCase(
            case_id=CASE_ID,
            reconciliation_id="reconciliation-1",
            status=status,
            assignee_user_id=assignee_id,
            revision=revision,
            created_by="system",
            created_at=NOW,
        ),
        items=[
            CaseItem(
                item_id=item_id,
                case_id=CASE_ID,
                item_type=CaseItemType.LINE,
                resolution_type=resolution,
                resolution_note="Existing note" if resolution else None,
                resolved_by=assignee_id if resolution else None,
                resolved_at=NOW if resolution else None,
                updated_at=NOW,
            )
            for item_id in ITEM_IDS
        ],
        actions=[],
    )


def service_for(
    *,
    status: CaseStatus = CaseStatus.IN_PROGRESS,
    assignee_id: str | None = "reviewer-a",
    resolution: ResolutionType | None = None,
    revision: int = 4,
) -> tuple[ReconciliationCaseService, FakeCaseRepository]:
    repository = FakeCaseRepository(
        case_bundle(
            status=status,
            assignee_id=assignee_id,
            resolution=resolution,
            revision=revision,
        )
    )
    return (
        ReconciliationCaseService(
            repository,
            active_reviewer_reader=FakeActiveReviewerReader({"reviewer-a", "reviewer-b"}),
        ),
        repository,
    )


def test_only_assignee_can_change_resolution() -> None:
    service, _ = service_for(revision=2)

    with pytest.raises(CaseError, match="CASE_ASSIGNEE_REQUIRED"):
        service.set_resolution(
            CASE_ID,
            ITEM_IDS[0],
            ResolutionType.BUSINESS_EXCEPTION,
            "Approved short delivery",
            user=reviewer("reviewer-b"),
            expected_revision=2,
        )


@pytest.mark.parametrize("operation", ["set_resolution", "submit_approval"])
def test_admin_with_assignee_id_cannot_edit_or_submit(operation: str) -> None:
    service, _ = service_for(resolution=ResolutionType.BUSINESS_EXCEPTION)
    same_id_admin = AuthenticatedUser(
        user_id="reviewer-a",
        username="admin-with-reviewer-id",
        role=AdminRole.ADMIN,
    )

    with pytest.raises(CaseError) as captured:
        if operation == "set_resolution":
            service.set_resolution(
                CASE_ID,
                ITEM_IDS[0],
                ResolutionType.BUSINESS_EXCEPTION,
                "Accepted",
                user=same_id_admin,
                expected_revision=4,
            )
        else:
            service.submit_approval(
                CASE_ID,
                user=same_id_admin,
                expected_revision=4,
            )

    assert captured.value.code == "CASE_ASSIGNEE_REQUIRED"


def test_business_exceptions_submit_for_approval() -> None:
    service, repository = service_for(
        resolution=ResolutionType.BUSINESS_EXCEPTION,
    )

    bundle = service.submit_approval(
        CASE_ID,
        user=reviewer(),
        expected_revision=4,
    )

    assert bundle.case.status == CaseStatus.PENDING_APPROVAL
    assert repository.actions[-1].action == CaseActionType.SUBMITTED_FOR_APPROVAL


@pytest.mark.parametrize(
    "resolution",
    [ResolutionType.DOCUMENT_DATA_ERROR, ResolutionType.MATCHING_ERROR],
)
def test_data_or_matching_error_can_only_submit_void(
    resolution: ResolutionType,
) -> None:
    service, _ = service_for(resolution=resolution)

    with pytest.raises(CaseError, match="CASE_SUBMISSION_CONFLICT"):
        service.submit_approval(CASE_ID, user=reviewer(), expected_revision=4)

    assert service.submit_void(
        CASE_ID, user=reviewer(), expected_revision=4
    ).case.status == CaseStatus.PENDING_VOID


@pytest.mark.parametrize(
    ("operation", "status", "actor", "expected_code"),
    [
        ("approve", CaseStatus.IN_PROGRESS, admin(), "CASE_INVALID_TRANSITION"),
        (
            "approve",
            CaseStatus.PENDING_APPROVAL,
            reviewer(),
            "CASE_ADMIN_REQUIRED",
        ),
        ("void", CaseStatus.PENDING_VOID, reviewer(), "CASE_ADMIN_REQUIRED"),
        ("claim", CaseStatus.IN_PROGRESS, reviewer(), "CASE_ALREADY_CLAIMED"),
        ("set_resolution", CaseStatus.APPROVED, reviewer(), "CASE_TERMINAL"),
        ("return_case", CaseStatus.VOIDED, admin(), "CASE_TERMINAL"),
    ],
)
def test_transition_guards(
    operation: str,
    status: CaseStatus,
    actor: AuthenticatedUser,
    expected_code: str,
) -> None:
    service, _ = service_for(status=status)

    with pytest.raises(CaseError) as captured:
        if operation == "approve":
            service.approve(CASE_ID, user=actor, expected_revision=4)
        elif operation == "void":
            service.void(CASE_ID, user=actor, expected_revision=4)
        elif operation == "claim":
            service.claim(CASE_ID, user=actor, expected_revision=4)
        elif operation == "set_resolution":
            service.set_resolution(
                CASE_ID,
                ITEM_IDS[0],
                ResolutionType.BUSINESS_EXCEPTION,
                "Valid note",
                user=actor,
                expected_revision=4,
            )
        else:
            service.return_case(
                CASE_ID,
                user=actor,
                reason="Clarify supplier approval",
                expected_revision=4,
            )

    assert captured.value.code == expected_code


@pytest.mark.parametrize(
    ("resolution", "expected_code"),
    [
        (None, "CASE_ITEMS_INCOMPLETE"),
        (ResolutionType.WAITING_FOR_DOCUMENTS, "CASE_ITEMS_INCOMPLETE"),
    ],
)
def test_waiting_and_unresolved_items_cannot_submit(
    resolution: ResolutionType | None,
    expected_code: str,
) -> None:
    service, _ = service_for(resolution=resolution)

    with pytest.raises(CaseError) as captured:
        service.submit_approval(CASE_ID, user=reviewer(), expected_revision=4)

    assert captured.value.code == expected_code


def test_return_and_reassign_require_reason_and_return_keeps_assignee() -> None:
    service, _ = service_for(
        status=CaseStatus.PENDING_APPROVAL,
        resolution=ResolutionType.BUSINESS_EXCEPTION,
    )

    with pytest.raises(ValueError, match="reason"):
        service.return_case(CASE_ID, user=admin(), reason=" ", expected_revision=4)
    returned = service.return_case(
        CASE_ID,
        user=admin(),
        reason="Clarify supplier approval",
        expected_revision=4,
    )
    assert returned.case.assignee_user_id == "reviewer-a"

    with pytest.raises(ValueError, match="reason"):
        service.reassign(
            CASE_ID,
            "reviewer-b",
            user=admin(),
            reason=" ",
            expected_revision=5,
        )


def test_reassign_requires_active_reviewer_and_records_reason() -> None:
    service, repository = service_for()

    with pytest.raises(CaseError, match="CASE_INVALID_ASSIGNEE"):
        service.reassign(
            CASE_ID,
            "unknown",
            user=admin(),
            reason="Rebalancing workload",
            expected_revision=4,
        )
    result = service.reassign(
        CASE_ID,
        "reviewer-b",
        user=admin(),
        reason="Rebalancing workload",
        expected_revision=4,
    )

    assert result.case.assignee_user_id == "reviewer-b"
    assert repository.actions[-1].action == CaseActionType.REASSIGNED
    assert repository.actions[-1].reason == "Rebalancing workload"


def test_claim_resolution_and_decision_create_one_action_per_mutation() -> None:
    service, repository = service_for(
        status=CaseStatus.UNASSIGNED,
        assignee_id=None,
        revision=1,
    )

    claimed = service.claim(CASE_ID, user=reviewer(), expected_revision=1)
    assert claimed.case.status == CaseStatus.IN_PROGRESS
    assert claimed.case.assignee_user_id == "reviewer-a"
    assert claimed.case.revision == 2
    assert repository.save_calls == 1

    resolved = service.set_resolution(
        CASE_ID,
        ITEM_IDS[0],
        ResolutionType.BUSINESS_EXCEPTION,
        "Accepted",
        user=reviewer(),
        expected_revision=2,
    )
    assert resolved.items[0].resolved_by == "reviewer-a"
    assert resolved.items[0].resolution_note == "Accepted"
    assert resolved.case.revision == 3
    assert repository.save_calls == 2


def test_blank_resolution_note_and_stale_revision_are_rejected() -> None:
    service, _ = service_for()

    with pytest.raises(ValueError, match="note"):
        service.set_resolution(
            CASE_ID,
            ITEM_IDS[0],
            ResolutionType.BUSINESS_EXCEPTION,
            "  ",
            user=reviewer(),
            expected_revision=4,
        )
    with pytest.raises(CaseError) as captured:
        service.claim(CASE_ID, user=reviewer(), expected_revision=3)

    assert captured.value.code == "CASE_REVISION_CONFLICT"
