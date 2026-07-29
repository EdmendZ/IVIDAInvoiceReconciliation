from typing import Protocol

from app.domain.admin_users import AuthenticatedUser
from app.domain.document_drafts import DraftBundle
from app.domain.document_versions import (
    DocumentVersion,
    DocumentVersionStatus,
    ReviewAction,
)
from app.domain.documents import DocumentType, Invoice, ReceiveNote
from app.infra.postgres_review_repository import (
    ApprovedVersionImmutable,
    PostgresReviewRepository,
    ReviewVersionNotFound,
)
from app.services.ports import DocumentDraftRepository
from app.services.validation_service import ValidationService


class UnresolvedBlockingIssues(RuntimeError):
    pass


class ReviewConflict(RuntimeError):
    pass


class ReviewService:
    def __init__(
        self,
        *,
        review_repository: PostgresReviewRepository,
        draft_repository: DocumentDraftRepository,
        validation_service: ValidationService,
    ) -> None:
        self._reviews = review_repository
        self._drafts = draft_repository
        self._validator = validation_service

    def start_review(
        self,
        task_id: str,
        user: AuthenticatedUser,
    ) -> DocumentVersion:
        latest = self._reviews.get_latest_version(task_id)
        if latest is not None:
            return latest
        bundle = self._drafts.get_for_task(task_id)
        if bundle is None:
            raise ReviewVersionNotFound(task_id)
        version = self._reviews.create_version(
            task_id=task_id,
            source_draft_id=bundle.draft.draft_id,
            document_type=bundle.draft.document_type.value,
            document_json=bundle.draft.normalized_json,
            created_by=user.user_id,
        )
        self._reviews.append_action(
            version_id=version.version_id,
            actor_user_id=user.user_id,
            action="review_started",
            reason="Created from normalized extraction draft",
        )
        return version

    def save_edit(
        self,
        version_id: str,
        document_json: dict,
        user: AuthenticatedUser,
        *,
        reason: str,
    ) -> DocumentVersion:
        current = self._require_version(version_id)
        latest = self._reviews.get_latest_version(current.task_id)
        if (
            current.status != DocumentVersionStatus.DRAFT
            or latest is None
            or latest.version_id != current.version_id
        ):
            raise ReviewConflict("A newer or immutable version exists")
        document = self._validate_document(
            current.document_type,
            document_json,
        )
        new_version = self._reviews.create_version(
            task_id=current.task_id,
            source_draft_id=current.source_draft_id,
            document_type=current.document_type.value,
            document_json=document.model_dump(mode="json"),
            created_by=user.user_id,
        )
        self._reviews.append_action(
            version_id=new_version.version_id,
            actor_user_id=user.user_id,
            action="document_edited",
            old_value=current.document_json,
            new_value=new_version.document_json,
            reason=reason.strip() or "Reviewer edit",
        )
        return new_version

    def approve(
        self,
        version_id: str,
        user: AuthenticatedUser,
        *,
        reason: str,
    ) -> DocumentVersion:
        current = self._require_version(version_id)
        document = self._validate_document(
            current.document_type,
            current.document_json,
        )
        report = self._validator.validate(document)
        if report.blocking_count:
            raise UnresolvedBlockingIssues(
                f"{report.blocking_count} blocking issue(s) remain"
            )
        approved = self._reviews.approve(version_id, user.user_id)
        self._reviews.append_action(
            version_id=version_id,
            actor_user_id=user.user_id,
            action="approved",
            reason=reason.strip() or "Verified by reviewer",
        )
        return approved

    def reject(
        self,
        version_id: str,
        user: AuthenticatedUser,
        *,
        reason: str,
    ) -> DocumentVersion:
        if not reason.strip():
            raise ValueError("Rejection reason is required")
        rejected = self._reviews.reject(version_id)
        self._reviews.append_action(
            version_id=version_id,
            actor_user_id=user.user_id,
            action="rejected",
            reason=reason.strip(),
        )
        return rejected

    def get(self, version_id: str) -> tuple[DocumentVersion, list[ReviewAction]]:
        version = self._require_version(version_id)
        return version, self._reviews.list_actions(version_id)

    def get_detail(self, version_id: str) -> dict:
        version, actions = self.get(version_id)
        bundle = self._drafts.get_for_task(version.task_id)
        return {
            "version": version.model_dump(mode="json"),
            "actions": [item.model_dump(mode="json") for item in actions],
            "evidence": (
                [item.model_dump(mode="json") for item in bundle.evidence]
                if bundle
                else []
            ),
            "issues": (
                [item.model_dump(mode="json") for item in bundle.issues]
                if bundle
                else []
            ),
        }

    def list_versions(
        self,
        status: DocumentVersionStatus | None = None,
    ) -> list[DocumentVersion]:
        return self._reviews.list_versions(status=status)

    def list_queue(self) -> list[dict]:
        versions = self._reviews.list_versions()
        by_task = {version.task_id: version for version in versions}
        result: list[dict] = []
        for bundle in self._drafts.list_latest():
            version = by_task.get(bundle.draft.task_id)
            result.append(
                {
                    "task_id": bundle.draft.task_id,
                    "version_id": version.version_id if version else None,
                    "version_number": version.version_number if version else None,
                    "status": (
                        version.status.value if version else "ready_for_review"
                    ),
                    "document_type": bundle.draft.document_type.value,
                    "document_number": bundle.draft.normalized_json.get(
                        "document_number"
                    ),
                    "supplier": (
                        bundle.draft.normalized_json.get("supplier") or {}
                    ).get("name"),
                    "validation_state": bundle.draft.validation_state.value,
                    "blocking_count": sum(
                        issue.severity.value == "blocking"
                        for issue in bundle.issues
                    ),
                    "warning_count": sum(
                        issue.severity.value == "warning"
                        for issue in bundle.issues
                    ),
                    "created_at": bundle.draft.created_at.isoformat(),
                }
            )
        return sorted(result, key=lambda item: item["created_at"], reverse=True)

    def _require_version(self, version_id: str) -> DocumentVersion:
        version = self._reviews.get_version(version_id)
        if version is None:
            raise ReviewVersionNotFound(version_id)
        return version

    @staticmethod
    def _validate_document(document_type: DocumentType, payload: dict):
        if document_type == DocumentType.INVOICE:
            return Invoice.model_validate(payload)
        return ReceiveNote.model_validate(payload)
