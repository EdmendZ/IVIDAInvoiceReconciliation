"""机器 Draft 到人工批准 Version 的治理边界。"""

from typing import Protocol

from pydantic import ValidationError

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
from app.services.ports import DocumentDraftRepository, ExtractionRunRepository
from app.services.validation_service import ValidationService


class UnresolvedBlockingIssues(RuntimeError):
    """批准时仍存在 Blocking Validation Issue。"""

    pass


class ReviewConflict(RuntimeError):
    """版本已过期、不可变或请求转换与当前状态冲突。"""

    pass


class DocumentTypeConfirmationMismatch(RuntimeError):
    """人工确认类型与待批准 Version 类型不一致。"""

    pass


class ReviewService:
    """负责版本创建、重分类、校验、批准以及审核动作记录。"""

    def __init__(
        self,
        *,
        review_repository: PostgresReviewRepository,
        draft_repository: DocumentDraftRepository,
        run_repository: ExtractionRunRepository,
        validation_service: ValidationService,
    ) -> None:
        self._reviews = review_repository
        self._drafts = draft_repository
        self._runs = run_repository
        self._validator = validation_service

    def start_review(
        self,
        task_id: str,
        user: AuthenticatedUser,
    ) -> DocumentVersion:
        """幂等地从机器 Draft 创建首个人工审核版本。"""

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
        """验证修改并创建新版本；从不覆盖已有 Version JSON。"""

        current = self._require_version(version_id)
        self._require_editable_latest(current)
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

    def reclassify(
        self,
        version_id: str,
        target_document_type: DocumentType,
        user: AuthenticatedUser,
        *,
        reason: str,
    ) -> DocumentVersion:
        """修正最新 Draft 的类型并创建带 old/new type 的审计版本。"""

        current = self._require_version(version_id)
        self._require_editable_latest(current)
        if target_document_type == current.document_type:
            raise ReviewConflict("Document already has the selected type")
        payload = dict(current.document_json)
        payload["document_type"] = target_document_type.value
        document = self._validate_document(target_document_type, payload)
        new_version = self._reviews.create_version(
            task_id=current.task_id,
            source_draft_id=current.source_draft_id,
            document_type=target_document_type.value,
            document_json=document.model_dump(mode="json"),
            created_by=user.user_id,
        )
        self._reviews.append_action(
            version_id=new_version.version_id,
            actor_user_id=user.user_id,
            action="document_reclassified",
            field_path="document_type",
            old_value=current.document_type.value,
            new_value=target_document_type.value,
            reason=reason.strip() or "Reviewer corrected document type",
        )
        return new_version

    def approve(
        self,
        version_id: str,
        user: AuthenticatedUser,
        *,
        reason: str,
        confirmed_document_type: DocumentType,
    ) -> DocumentVersion:
        """在最新版本、类型确认和无阻断问题的前提下批准。"""

        current = self._require_version(version_id)
        self._require_editable_latest(current)
        if confirmed_document_type != current.document_type:
            raise DocumentTypeConfirmationMismatch(
                "Confirmed document type does not match the reviewed version"
            )
        document = self._validate_document(
            current.document_type,
            current.document_json,
        )
        # 前端 Live Validation 仅改善体验；批准时必须在服务端重新验证。
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
        """要求非空原因后驳回当前 Version。"""

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
        """同时返回 Version 与按时间排序的审核动作。"""

        version = self._require_version(version_id)
        return version, self._reviews.list_actions(version_id)

    def get_detail(self, version_id: str) -> dict:
        """组合版本、Evidence、Issue、动作和安全的模型溯源信息。"""

        version, actions = self.get(version_id)
        bundle = self._drafts.get_for_task(version.task_id)
        run = self._runs.get(bundle.draft.run_id) if bundle else None
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
            "model_run": (
                {
                    "run_id": run.run_id,
                    "parser_provider": run.parser_provider or run.provider,
                    "parser_model": run.parser_model or run.model_name,
                    "normalizer_provider": run.normalizer_provider,
                    "normalizer_model": run.normalizer_model,
                    "prompt_version": run.prompt_version,
                    "normalization_latency_ms": run.normalization_latency_ms,
                    "input_tokens": run.input_tokens,
                    "output_tokens": run.output_tokens,
                    "estimated_cost_aud": (
                        str(run.estimated_cost_aud)
                        if run.estimated_cost_aud is not None
                        else None
                    ),
                }
                if run
                else None
            ),
        }

    def preview_validation(
        self,
        version_id: str,
        document_json: dict,
    ) -> dict:
        """将 Pydantic/业务规则转换成前端统一的预览结构。"""

        current = self._require_version(version_id)
        try:
            document = self._validate_document(
                current.document_type,
                document_json,
            )
        except ValidationError as exc:
            issues = [
                {
                    "rule_code": "SCHEMA_INVALID",
                    "severity": "blocking",
                    "field_path": ".".join(str(part) for part in error["loc"]),
                    "message": error["msg"],
                    "measured_difference": None,
                }
                for error in exc.errors(include_url=False)
            ]
            return {
                "schema_valid": False,
                "blocking_count": len(issues),
                "warning_count": 0,
                "issues": issues,
            }
        report = self._validator.validate(document)
        return {
            "schema_valid": True,
            "blocking_count": report.blocking_count,
            "warning_count": report.warning_count,
            "issues": [
                issue.model_dump(mode="json") for issue in report.issues
            ],
        }

    def list_versions(
        self,
        status: DocumentVersionStatus | None = None,
    ) -> list[DocumentVersion]:
        """按可选状态列出人工 Version。"""

        return self._reviews.list_versions(status=status)

    def list_queue(self) -> list[dict]:
        """为审核队列组合每个 Task 最新 Version 与机器问题摘要。"""

        versions = self._reviews.list_versions()
        by_task: dict[str, DocumentVersion] = {}
        for version in versions:
            by_task.setdefault(version.task_id, version)
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
                    "document_type": (
                        version.document_type.value
                        if version
                        else bundle.draft.document_type.value
                    ),
                    "document_number": (
                        version.document_json.get("document_number")
                        if version
                        else bundle.draft.normalized_json.get("document_number")
                    ),
                    "supplier": (
                        (
                            version.document_json.get("supplier")
                            if version
                            else bundle.draft.normalized_json.get("supplier")
                        )
                        or {}
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

    def _require_editable_latest(self, current: DocumentVersion) -> None:
        """阻止旧版本或终态版本继续编辑，避免产生分叉历史。"""

        latest = self._reviews.get_latest_version(current.task_id)
        if (
            current.status != DocumentVersionStatus.DRAFT
            or latest is None
            or latest.version_id != current.version_id
        ):
            raise ReviewConflict("A newer or immutable version exists")

    @staticmethod
    def _validate_document(document_type: DocumentType, payload: dict):
        if document_type == DocumentType.INVOICE:
            return Invoice.model_validate(payload)
        return ReceiveNote.model_validate(payload)
