"""State transitions and permissions for reconciliation exception cases."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from app.domain.admin_users import AdminRole, AuthenticatedUser
from app.domain.reconciliation_cases import (
    CaseAction,
    CaseActionType,
    CaseItem,
    CaseListQuery,
    CasePage,
    CaseStatus,
    ReconciliationCase,
    ReconciliationCaseBundle,
    ResolutionType,
)


class CaseError(RuntimeError):
    """A stable business error suitable for API error mapping."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class ReconciliationCaseRepository(Protocol):
    """Atomic persistence boundary for case and item mutations."""

    def get_bundle(self, case_id: str) -> ReconciliationCaseBundle | None: ...

    def list_cases(self, query: CaseListQuery, user_id: str) -> CasePage: ...

    def save_case_mutation(
        self,
        bundle: ReconciliationCaseBundle,
        action: CaseAction,
        *,
        expected_revision: int,
    ) -> ReconciliationCaseBundle: ...


class ActiveReviewerReader(Protocol):
    """Read-only account lookup used when an admin reassigns a case."""

    def is_active_reviewer(self, user_id: str) -> bool: ...


TERMINAL = {CaseStatus.APPROVED, CaseStatus.VOIDED}


def _require_revision(case: ReconciliationCase, expected: int) -> None:
    if case.revision != expected:
        raise CaseError("CASE_REVISION_CONFLICT", "Case has changed; refresh and retry")


def _require_assignee(case: ReconciliationCase, user: AuthenticatedUser) -> None:
    if case.assignee_user_id != user.user_id:
        raise CaseError("CASE_ASSIGNEE_REQUIRED", "Only the assignee can edit this case")


def _require_admin(user: AuthenticatedUser) -> None:
    if user.role != AdminRole.ADMIN:
        raise CaseError("CASE_ADMIN_REQUIRED", "Admin role required")


def _submission_target(items: list[CaseItem]) -> CaseStatus:
    if any(item.resolution_type is None for item in items):
        raise CaseError(
            "CASE_ITEMS_INCOMPLETE",
            "Every case item requires a resolution",
        )
    if any(
        item.resolution_type == ResolutionType.WAITING_FOR_DOCUMENTS
        for item in items
    ):
        raise CaseError("CASE_ITEMS_INCOMPLETE", "Documents are still outstanding")
    kinds = {item.resolution_type for item in items}
    if kinds == {ResolutionType.BUSINESS_EXCEPTION}:
        return CaseStatus.PENDING_APPROVAL
    if kinds & {ResolutionType.DOCUMENT_DATA_ERROR, ResolutionType.MATCHING_ERROR}:
        return CaseStatus.PENDING_VOID
    raise CaseError(
        "CASE_SUBMISSION_CONFLICT",
        "Resolution combination cannot be submitted",
    )


class ReconciliationCaseService:
    """Enforces the Case workflow before passing one atomic mutation to storage."""

    def __init__(
        self,
        repository: ReconciliationCaseRepository,
        *,
        active_reviewer_reader: ActiveReviewerReader,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._reviewers = active_reviewer_reader
        self._now = now or (lambda: datetime.now(UTC))

    def claim(
        self,
        case_id: str,
        *,
        user: AuthenticatedUser,
        expected_revision: int,
    ) -> ReconciliationCaseBundle:
        bundle = self._load_mutable(case_id, expected_revision)
        case = bundle.case
        if case.status != CaseStatus.UNASSIGNED or case.assignee_user_id is not None:
            raise CaseError("CASE_ALREADY_CLAIMED", "Case has already been claimed")
        if user.role != AdminRole.REVIEWER:
            raise CaseError("CASE_REVIEWER_REQUIRED", "Reviewer role required")

        now = self._now()
        updated = bundle.model_copy(
            update={
                "case": case.model_copy(
                    update={
                        "status": CaseStatus.IN_PROGRESS,
                        "assignee_user_id": user.user_id,
                        "claimed_at": now,
                    }
                )
            }
        )
        return self._save(
            updated,
            self._action(
                case_id,
                user.user_id,
                CaseActionType.CLAIMED,
                old_value=None,
                new_value=user.user_id,
                now=now,
            ),
            expected_revision,
        )

    def reassign(
        self,
        case_id: str,
        target_user_id: str,
        *,
        user: AuthenticatedUser,
        reason: str,
        expected_revision: int,
    ) -> ReconciliationCaseBundle:
        bundle = self._load_mutable(case_id, expected_revision)
        case = bundle.case
        _require_admin(user)
        if case.status == CaseStatus.UNASSIGNED or case.assignee_user_id is None:
            raise CaseError(
                "CASE_INVALID_TRANSITION",
                "Only an assigned case can be reassigned",
            )
        reason = self._required_text(reason, "Reassignment reason")
        if not self._reviewers.is_active_reviewer(target_user_id):
            raise CaseError(
                "CASE_INVALID_ASSIGNEE",
                "Assignee must be an active reviewer",
            )

        now = self._now()
        updated = bundle.model_copy(
            update={
                "case": case.model_copy(update={"assignee_user_id": target_user_id})
            }
        )
        return self._save(
            updated,
            self._action(
                case_id,
                user.user_id,
                CaseActionType.REASSIGNED,
                old_value=case.assignee_user_id,
                new_value=target_user_id,
                reason=reason,
                now=now,
            ),
            expected_revision,
        )

    def set_resolution(
        self,
        case_id: str,
        item_id: str,
        resolution_type: ResolutionType,
        note: str,
        *,
        user: AuthenticatedUser,
        expected_revision: int,
    ) -> ReconciliationCaseBundle:
        bundle = self._load_mutable(case_id, expected_revision)
        case = bundle.case
        _require_assignee(case, user)
        self._require_status(case, CaseStatus.IN_PROGRESS)
        note = self._required_text(note, "Resolution note")
        item = next((candidate for candidate in bundle.items if candidate.item_id == item_id), None)
        if item is None:
            raise CaseError("CASE_ITEM_NOT_FOUND", "Case item was not found")

        now = self._now()
        updated_item = item.model_copy(
            update={
                "resolution_type": resolution_type,
                "resolution_note": note,
                "resolved_by": user.user_id,
                "resolved_at": now,
                "updated_at": now,
            }
        )
        updated = bundle.model_copy(
            update={
                "items": [
                    updated_item if candidate.item_id == item_id else candidate
                    for candidate in bundle.items
                ]
            }
        )
        return self._save(
            updated,
            self._action(
                case_id,
                user.user_id,
                CaseActionType.RESOLUTION_CHANGED,
                item_id=item_id,
                old_value={
                    "resolution_type": item.resolution_type,
                    "resolution_note": item.resolution_note,
                },
                new_value={
                    "resolution_type": resolution_type,
                    "resolution_note": note,
                },
                now=now,
            ),
            expected_revision,
        )

    def submit_approval(
        self,
        case_id: str,
        *,
        user: AuthenticatedUser,
        expected_revision: int,
    ) -> ReconciliationCaseBundle:
        return self._submit(
            case_id,
            user=user,
            expected_revision=expected_revision,
            requested_status=CaseStatus.PENDING_APPROVAL,
            action_type=CaseActionType.SUBMITTED_FOR_APPROVAL,
        )

    def submit_void(
        self,
        case_id: str,
        *,
        user: AuthenticatedUser,
        expected_revision: int,
    ) -> ReconciliationCaseBundle:
        return self._submit(
            case_id,
            user=user,
            expected_revision=expected_revision,
            requested_status=CaseStatus.PENDING_VOID,
            action_type=CaseActionType.SUBMITTED_FOR_VOID,
        )

    def approve(
        self,
        case_id: str,
        *,
        user: AuthenticatedUser,
        expected_revision: int,
    ) -> ReconciliationCaseBundle:
        return self._complete(
            case_id,
            user=user,
            expected_revision=expected_revision,
            required_status=CaseStatus.PENDING_APPROVAL,
            target_status=CaseStatus.APPROVED,
            required_submission=CaseStatus.PENDING_APPROVAL,
            action_type=CaseActionType.APPROVED,
        )

    def return_case(
        self,
        case_id: str,
        *,
        user: AuthenticatedUser,
        reason: str,
        expected_revision: int,
    ) -> ReconciliationCaseBundle:
        bundle = self._load_mutable(case_id, expected_revision)
        case = bundle.case
        _require_admin(user)
        if case.status not in {CaseStatus.PENDING_APPROVAL, CaseStatus.PENDING_VOID}:
            raise CaseError("CASE_INVALID_TRANSITION", "Case is not pending a decision")
        reason = self._required_text(reason, "Return reason")

        now = self._now()
        updated = bundle.model_copy(
            update={
                "case": case.model_copy(
                    update={"status": CaseStatus.IN_PROGRESS, "submitted_at": None}
                )
            }
        )
        return self._save(
            updated,
            self._action(
                case_id,
                user.user_id,
                CaseActionType.RETURNED,
                old_value=case.status,
                new_value=CaseStatus.IN_PROGRESS,
                reason=reason,
                now=now,
            ),
            expected_revision,
        )

    def void(
        self,
        case_id: str,
        *,
        user: AuthenticatedUser,
        expected_revision: int,
    ) -> ReconciliationCaseBundle:
        return self._complete(
            case_id,
            user=user,
            expected_revision=expected_revision,
            required_status=CaseStatus.PENDING_VOID,
            target_status=CaseStatus.VOIDED,
            required_submission=CaseStatus.PENDING_VOID,
            action_type=CaseActionType.VOIDED,
        )

    def get_detail(self, case_id: str) -> ReconciliationCaseBundle:
        """Return the current aggregate; richer presentation joins are repository concerns."""
        return self._load(case_id)

    def list_cases(self, query: CaseListQuery, *, user: AuthenticatedUser) -> CasePage:
        return self._repository.list_cases(query, user.user_id)

    def _submit(
        self,
        case_id: str,
        *,
        user: AuthenticatedUser,
        expected_revision: int,
        requested_status: CaseStatus,
        action_type: CaseActionType,
    ) -> ReconciliationCaseBundle:
        bundle = self._load_mutable(case_id, expected_revision)
        case = bundle.case
        _require_assignee(case, user)
        self._require_status(case, CaseStatus.IN_PROGRESS)
        if _submission_target(bundle.items) != requested_status:
            raise CaseError(
                "CASE_SUBMISSION_CONFLICT",
                "Selected submission does not match item resolutions",
            )

        now = self._now()
        updated = bundle.model_copy(
            update={
                "case": case.model_copy(
                    update={"status": requested_status, "submitted_at": now}
                )
            }
        )
        return self._save(
            updated,
            self._action(
                case_id,
                user.user_id,
                action_type,
                old_value=case.status,
                new_value=requested_status,
                now=now,
            ),
            expected_revision,
        )

    def _complete(
        self,
        case_id: str,
        *,
        user: AuthenticatedUser,
        expected_revision: int,
        required_status: CaseStatus,
        target_status: CaseStatus,
        required_submission: CaseStatus,
        action_type: CaseActionType,
    ) -> ReconciliationCaseBundle:
        bundle = self._load_mutable(case_id, expected_revision)
        case = bundle.case
        _require_admin(user)
        self._require_status(case, required_status)
        if _submission_target(bundle.items) != required_submission:
            raise CaseError(
                "CASE_SUBMISSION_CONFLICT",
                "Item resolutions do not support this decision",
            )

        now = self._now()
        updated = bundle.model_copy(
            update={
                "case": case.model_copy(
                    update={"status": target_status, "completed_at": now}
                )
            }
        )
        return self._save(
            updated,
            self._action(
                case_id,
                user.user_id,
                action_type,
                old_value=case.status,
                new_value=target_status,
                now=now,
            ),
            expected_revision,
        )

    def _load(self, case_id: str) -> ReconciliationCaseBundle:
        bundle = self._repository.get_bundle(case_id)
        if bundle is None:
            raise CaseError("CASE_NOT_FOUND", "Case was not found")
        return bundle

    def _load_mutable(
        self,
        case_id: str,
        expected_revision: int,
    ) -> ReconciliationCaseBundle:
        bundle = self._load(case_id)
        if bundle.case.status in TERMINAL:
            raise CaseError("CASE_TERMINAL", "Terminal cases cannot be changed")
        _require_revision(bundle.case, expected_revision)
        return bundle

    @staticmethod
    def _required_text(value: str, field: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{field} is required")
        return normalized

    @staticmethod
    def _require_status(case: ReconciliationCase, expected: CaseStatus) -> None:
        if case.status != expected:
            raise CaseError("CASE_INVALID_TRANSITION", "Case is not in the required state")

    def _save(
        self,
        bundle: ReconciliationCaseBundle,
        action: CaseAction,
        expected_revision: int,
    ) -> ReconciliationCaseBundle:
        return self._repository.save_case_mutation(
            bundle,
            action,
            expected_revision=expected_revision,
        )

    @staticmethod
    def _action(
        case_id: str,
        actor_user_id: str,
        action: CaseActionType,
        *,
        item_id: str | None = None,
        old_value: object | None = None,
        new_value: object | None = None,
        reason: str | None = None,
        now: datetime,
    ) -> CaseAction:
        return CaseAction(
            action_id=str(uuid4()),
            case_id=case_id,
            item_id=item_id,
            actor_user_id=actor_user_id,
            action=action,
            old_value=old_value,
            new_value=new_value,
            reason=reason,
            created_at=now,
        )
