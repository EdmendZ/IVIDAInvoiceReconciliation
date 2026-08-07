from datetime import UTC, datetime, timedelta

import pytest

from app.domain.admin_users import AdminRole, AuthenticatedUser
from app.domain.document_drafts import DocumentDraft, DraftBundle, DraftValidationState
from app.domain.document_versions import (
    DocumentVersion,
    DocumentVersionStatus,
    ReviewAction,
)
from app.domain.documents import DocumentType
from app.domain.extraction_runs import ExtractionRun, ExtractionRunStatus
from app.experiments.domain import FeedbackClassification
from app.experiments.feedback import (
    FeedbackPermissionDenied,
    FeedbackService,
    iter_field_changes,
)


NOW = datetime(2026, 8, 7, tzinfo=UTC)


class Reviews:
    def __init__(self, version, actions) -> None:
        self.version = version
        self.actions = actions

    def get_version(self, version_id):
        return self.version if version_id == self.version.version_id else None

    def list_actions(self, version_id):
        return self.actions if version_id == self.version.version_id else []


class Drafts:
    def __init__(self, bundle) -> None:
        self.bundle = bundle

    def get_for_task(self, task_id):
        return self.bundle if task_id == self.bundle.draft.task_id else None


class Runs:
    def __init__(self, run) -> None:
        self.run = run

    def get(self, run_id):
        return self.run if run_id == self.run.run_id else None


class Experiments:
    def __init__(self) -> None:
        self.candidates = {}

    def list_feedback_candidates(self, *, confirmed=None):
        values = list(self.candidates.values())
        if confirmed is True:
            return [item for item in values if item.confirmed_at is not None]
        if confirmed is False:
            return [item for item in values if item.confirmed_at is None]
        return values

    def create_feedback_candidates(self, candidates):
        for candidate in candidates:
            self.candidates[candidate.candidate_id] = candidate
        return candidates

    def confirm_feedback(
        self,
        candidate_id,
        *,
        classification,
        include_in_gold,
        confirmed_by,
        confirmed_at,
    ):
        candidate = self.candidates[candidate_id].model_copy(
            update={
                "classification": classification,
                "include_in_gold": include_in_gold
                and classification == FeedbackClassification.MODEL_ERROR,
                "confirmed_by": confirmed_by,
                "confirmed_at": confirmed_at,
            }
        )
        self.candidates[candidate_id] = candidate
        return candidate


def _service():
    old_document = {
        "document_type": "invoice",
        "supplier": {"name": "SYNTHETIC DOCUMENT"},
        "items": [
            {"sku": "A-1", "description": "Cheese", "quantity": "1"},
            {"description": " Tomato  Sauce ", "quantity": "2"},
        ],
    }
    new_document = {
        "document_type": "invoice",
        "supplier": {"name": "Southern Cross Foodservice"},
        "items": [
            {"description": "tomato sauce", "quantity": "3"},
            {"sku": "A-1", "description": "Cheese", "quantity": "1"},
        ],
    }
    version = DocumentVersion(
        version_id="version-1",
        task_id="task-1",
        source_draft_id="draft-1",
        version_number=2,
        document_type=DocumentType.INVOICE,
        document_json=new_document,
        status=DocumentVersionStatus.DRAFT,
        created_by="reviewer-1",
        created_at=NOW,
    )
    action = ReviewAction(
        action_id="action-1",
        version_id=version.version_id,
        actor_user_id="reviewer-1",
        action="document_edited",
        old_value=old_document,
        new_value=new_document,
        created_at=NOW,
    )
    draft = DocumentDraft(
        draft_id="draft-1",
        run_id="run-1",
        task_id="task-1",
        document_type=DocumentType.INVOICE,
        normalized_json=old_document,
        validation_state=DraftValidationState.REVIEWABLE,
        created_at=NOW,
        updated_at=NOW,
    )
    run = ExtractionRun(
        run_id="run-1",
        task_id="task-1",
        provider="mineru",
        model_name="vlm",
        status=ExtractionRunStatus.READY_FOR_REVIEW,
        normalizer_model="qwen-plus",
        prompt_version="sha256:prompt",
        started_at=NOW,
        created_at=NOW,
    )
    experiments = Experiments()
    service = FeedbackService(
        review_repository=Reviews(version, [action]),
        draft_repository=Drafts(DraftBundle(draft=draft, evidence=[], issues=[])),
        run_repository=Runs(run),
        experiment_repository=experiments,
    )
    return service, experiments


def test_edit_generates_recursive_and_stable_line_candidates() -> None:
    service, _ = _service()

    candidates = service.collect_for_version("version-1")

    changes = {(item.field_path, item.old_value, item.new_value) for item in candidates}
    assert (
        "supplier.name",
        "SYNTHETIC DOCUMENT",
        "Southern Cross Foodservice",
    ) in changes
    assert ("items[description=tomato sauce].quantity", "2", "3") in changes
    assert all("items[0]" not in item.field_path for item in candidates)


def test_collection_is_idempotent() -> None:
    service, experiments = _service()

    first = service.collect_for_version("version-1")
    second = service.collect_for_version("version-1")

    assert second == first
    assert len(experiments.candidates) == len(first)


def test_only_model_error_enters_gold() -> None:
    service, _ = _service()
    candidate = service.collect_for_version("version-1")[0]
    admin = AuthenticatedUser(user_id="admin-1", username="admin", role=AdminRole.ADMIN)

    confirmed = service.confirm(
        candidate.candidate_id,
        FeedbackClassification.ACCEPTABLE_VARIANT,
        True,
        admin,
        NOW,
    )

    assert confirmed.include_in_gold is False


def test_reviewer_cannot_confirm_feedback() -> None:
    service, _ = _service()
    candidate = service.collect_for_version("version-1")[0]
    reviewer = AuthenticatedUser(
        user_id="reviewer-1", username="reviewer", role=AdminRole.REVIEWER
    )

    with pytest.raises(FeedbackPermissionDenied):
        service.confirm(
            candidate.candidate_id,
            FeedbackClassification.MODEL_ERROR,
            True,
            reviewer,
            NOW,
        )


def test_changed_judgment_supersedes_confirmed_candidate() -> None:
    service, experiments = _service()
    candidate = service.collect_for_version("version-1")[0]
    admin = AuthenticatedUser(user_id="admin-1", username="admin", role=AdminRole.ADMIN)
    service.confirm(
        candidate.candidate_id,
        FeedbackClassification.MODEL_ERROR,
        True,
        admin,
        NOW,
    )

    replacement = service.confirm(
        candidate.candidate_id,
        FeedbackClassification.BUSINESS_CONTEXT_UPDATE,
        True,
        admin,
        NOW + timedelta(minutes=1),
    )

    assert replacement.candidate_id != candidate.candidate_id
    assert replacement.supersedes_candidate_id == candidate.candidate_id
    assert replacement.include_in_gold is False
    assert len(experiments.candidates) > 1


def test_unstable_lines_are_reported_as_a_whole_list_change() -> None:
    changes = list(
        iter_field_changes(
            {"items": [{"quantity": 1}]},
            {"items": [{"quantity": 2}]},
        )
    )
    assert changes == [("items", [{"quantity": 1}], [{"quantity": 2}])]


def test_line_can_gain_sku_without_becoming_delete_and_add() -> None:
    changes = list(
        iter_field_changes(
            {"items": [{"description": "Cheese", "quantity": 1}]},
            {"items": [{"sku": "A-1", "description": "cheese", "quantity": 2}]},
        )
    )
    assert ("items[sku=a-1].quantity", 1, 2) in changes
    assert all("]." in path for path, _, _ in changes)
