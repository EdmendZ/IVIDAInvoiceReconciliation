"""Workspace user use cases over the atomic repository boundary."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
from decimal import Decimal
from uuid import UUID

from app.domain.admin_users import AdminRole, AuthenticatedUser
from app.domain.workspace import (
    ActionPage,
    ConfirmationResponse,
    ConfirmationView,
    DocumentDetail,
    DocumentPage,
    DocumentQuery,
    DocumentSummary,
    EditCommand,
    ConfirmCommand,
    IntakeResponse,
    InvestigateCommand,
    ReasonCommand,
    RetryResponse,
    RevisionCommand,
    RuntimeView,
    SelectionCommand,
    SourceFile,
    UploadCommand,
    WorkspaceCommand,
    WorkspaceError,
    WorkspaceErrorCode,
    WorkspaceOperation,
    WorkspaceScopeKey,
)
from app.services.document_upload_service import (
    DocumentUploadService,
    DocumentValidationError,
)
from app.services.ports import ObjectStorage
from app.services.workspace_ports import WorkspaceRepository


logger = logging.getLogger(__name__)

_CSV_COLUMNS = [
    "confirmation_id",
    "invoice_number",
    "receive_note_numbers",
    "rule_version",
    "resolution",
    "note",
    "match_key",
    "sku",
    "description",
    "invoice_quantity",
    "received_quantity",
    "quantity_difference",
    "quantity_status",
    "price_status",
    "amount_status",
]


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _request_hash(method: str, path: str, body: object) -> str:
    canonical = _canonical_json(body)
    return hashlib.sha256(f"{method}{path}{canonical}".encode("utf-8")).hexdigest()


def _model_body(command: WorkspaceCommand) -> dict:
    return command.model_dump(mode="json")


def _safe_text(value: str) -> str:
    if value.startswith(("=", "+", "-", "@", "\t", "\r")):
        return f"'{value}"
    return value


def _decimal_text(value: Decimal | None) -> str:
    if value is None:
        return ""
    if not isinstance(value, Decimal):
        raise TypeError("CSV numeric cells require Decimal values")
    return str(value)


class WorkspaceService:
    """Authorize users and delegate atomic state changes to the repository."""

    def __init__(
        self,
        repository: WorkspaceRepository,
        upload_service: DocumentUploadService,
        storage: ObjectStorage,
        scope: WorkspaceScopeKey,
    ) -> None:
        self._repository = repository
        self._upload_service = upload_service
        self._storage = storage
        self._scope = scope

    @staticmethod
    def _actor_id(actor: AuthenticatedUser) -> str:
        if actor.role not in {AdminRole.REVIEWER, AdminRole.ADMIN}:
            raise WorkspaceError(
                WorkspaceErrorCode.FORBIDDEN,
                "当前账号无权执行此操作",
            )
        return actor.user_id

    @staticmethod
    def _key(key: str) -> str:
        try:
            return str(UUID(key))
        except (TypeError, ValueError, AttributeError) as exc:
            raise WorkspaceError(
                WorkspaceErrorCode.INVALID_REQUEST,
                "请求标识必须是有效的 UUID",
            ) from exc

    def _mutate(
        self,
        *,
        document_id: str,
        operation: WorkspaceOperation,
        command: WorkspaceCommand,
        actor: AuthenticatedUser,
        key: str,
        method: str,
        suffix: str,
    ):
        actor_id = self._actor_id(actor)
        normalized_key = self._key(key)
        path = f"/api/workspace/documents/{document_id}{suffix}"
        request_hash = _request_hash(method, path, _model_body(command))
        return self._repository.mutate(
            self._scope,
            document_id,
            operation,
            command,
            actor_id,
            normalized_key,
            request_hash,
        )

    def _delete_prepared(self, object_key: str, *, task_id: str) -> None:
        try:
            self._storage.delete(object_key)
        except Exception:
            logger.exception(
                "Failed to compensate unused workspace upload",
                extra={"task_id": task_id},
            )

    def upload(
        self,
        command: UploadCommand,
        actor: AuthenticatedUser,
        key: str,
    ) -> IntakeResponse:
        actor_id = self._actor_id(actor)
        normalized_key = self._key(key)
        file_sha256 = hashlib.sha256(command.data).hexdigest()
        request_hash = _request_hash(
            "POST",
            "/api/workspace/documents",
            {
                "document_type": command.document_type.value,
                "file_sha256": file_sha256,
                "filename": command.filename,
            },
        )

        cached = self._repository.cached_request(
            self._scope,
            actor_id,
            normalized_key,
            request_hash,
        )
        if cached is not None:
            return IntakeResponse.model_validate(cached.body)

        try:
            prepared = self._upload_service.prepare_upload(
                document_type=command.document_type,
                filename=command.filename,
                data=command.data,
            )
        except DocumentValidationError as exc:
            raise WorkspaceError(
                WorkspaceErrorCode.INVALID_FILE,
                "文件格式、名称或大小不符合要求",
            ) from exc
        except Exception as exc:
            raise WorkspaceError(
                WorkspaceErrorCode.STORAGE_UNAVAILABLE,
                "原件存储暂不可用，请稍后重试",
            ) from exc

        try:
            response = self._repository.intake(
                self._scope,
                prepared,
                actor_id,
                normalized_key,
                request_hash,
            )
        except Exception:
            self._delete_prepared(
                prepared.task.storage_object_key,
                task_id=prepared.task.task_id,
            )
            raise

        if response.task_id != prepared.task.task_id:
            self._delete_prepared(
                prepared.task.storage_object_key,
                task_id=prepared.task.task_id,
            )
        return response

    def list_documents(self, query: DocumentQuery) -> DocumentPage:
        return self._repository.list_documents(self._scope, query)

    def get_document(self, document_id: str) -> DocumentDetail:
        return self._repository.get_document(self._scope, document_id)

    def get_actions(self, document_id: str, page: int, page_size: int) -> ActionPage:
        return self._repository.get_actions(
            self._scope, document_id, page, page_size
        )

    def edit(
        self,
        document_id: str,
        command: EditCommand,
        actor: AuthenticatedUser,
        key: str,
    ) -> DocumentSummary:
        return self._mutate(
            document_id=document_id,
            operation=WorkspaceOperation.EDIT,
            command=command,
            actor=actor,
            key=key,
            method="PATCH",
            suffix="",
        )

    def select(
        self,
        document_id: str,
        command: SelectionCommand,
        actor: AuthenticatedUser,
        key: str,
    ) -> DocumentSummary:
        return self._mutate(
            document_id=document_id,
            operation=WorkspaceOperation.SELECT,
            command=command,
            actor=actor,
            key=key,
            method="PUT",
            suffix="/selection",
        )

    def investigate(
        self,
        document_id: str,
        command: InvestigateCommand,
        actor: AuthenticatedUser,
        key: str,
    ) -> DocumentSummary:
        return self._mutate(
            document_id=document_id,
            operation=WorkspaceOperation.INVESTIGATE,
            command=command,
            actor=actor,
            key=key,
            method="POST",
            suffix="/investigate",
        )

    def confirm(
        self,
        document_id: str,
        command: ConfirmCommand,
        actor: AuthenticatedUser,
        key: str,
    ) -> ConfirmationResponse:
        return self._mutate(
            document_id=document_id,
            operation=WorkspaceOperation.CONFIRM,
            command=command,
            actor=actor,
            key=key,
            method="POST",
            suffix="/confirm",
        )

    def reopen(
        self,
        document_id: str,
        command: ReasonCommand,
        actor: AuthenticatedUser,
        key: str,
    ) -> DocumentSummary:
        return self._mutate(
            document_id=document_id,
            operation=WorkspaceOperation.REOPEN,
            command=command,
            actor=actor,
            key=key,
            method="POST",
            suffix="/reopen",
        )

    def void(
        self,
        document_id: str,
        command: ReasonCommand,
        actor: AuthenticatedUser,
        key: str,
    ) -> DocumentSummary:
        return self._mutate(
            document_id=document_id,
            operation=WorkspaceOperation.VOID,
            command=command,
            actor=actor,
            key=key,
            method="POST",
            suffix="/void",
        )

    def retry(
        self,
        document_id: str,
        command: RevisionCommand,
        actor: AuthenticatedUser,
        key: str,
    ) -> RetryResponse:
        return self._mutate(
            document_id=document_id,
            operation=WorkspaceOperation.RETRY,
            command=command,
            actor=actor,
            key=key,
            method="POST",
            suffix="/retry",
        )

    def get_confirmation(self, confirmation_id: str) -> ConfirmationView:
        return self._repository.get_confirmation(self._scope, confirmation_id)

    def source(self, document_id: str) -> SourceFile:
        metadata = self._repository.source_metadata(self._scope, document_id)
        try:
            data = self._storage.get(metadata.object_key)
        except Exception as exc:
            raise WorkspaceError(
                WorkspaceErrorCode.STORAGE_UNAVAILABLE,
                "原件存储暂不可用，请稍后重试",
            ) from exc
        return SourceFile(
            filename=metadata.filename,
            content_type=metadata.content_type,
            data=data,
        )

    def export(self, confirmation_id: str) -> str:
        confirmation = self.get_confirmation(confirmation_id)
        output = io.StringIO(newline="")
        rows = csv.writer(output, lineterminator="\r\n")
        rows.writerow(_CSV_COLUMNS)
        common = [
            confirmation.confirmation_id,
            _safe_text(confirmation.invoice_number),
            _safe_text(", ".join(confirmation.receive_note_numbers)),
            confirmation.rule_version,
            confirmation.resolution.value,
            _safe_text(confirmation.note or ""),
        ]
        for line in confirmation.result_snapshot.lines:
            rows.writerow(
                [
                    *common,
                    _safe_text(line.match_key),
                    _safe_text(line.sku or ""),
                    _safe_text(line.description),
                    _decimal_text(line.quantity.invoice_value),
                    _decimal_text(line.quantity.received_value),
                    _decimal_text(line.quantity.difference),
                    line.quantity.status.value,
                    line.price.status.value,
                    line.amount.status.value,
                ]
            )
        return "\ufeff" + output.getvalue()

    def runtime(self) -> RuntimeView:
        return self._repository.runtime(self._scope)
