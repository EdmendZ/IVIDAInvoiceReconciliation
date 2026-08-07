"""人工审核版本及追加式审核动作。"""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.domain.document_sources import (
    DocumentSourceKind,
    DocumentTrustMethod,
    UpstreamRecordStatus,
)
from app.domain.documents import DocumentType


class DocumentVersionStatus(StrEnum):
    """人工版本的可编辑与终结状态。"""

    DRAFT = "draft"
    APPROVED = "approved"
    REJECTED = "rejected"


class DocumentVersion(BaseModel):
    """人工审核产生的版本快照；Approved/Rejected 后不可覆盖。"""

    version_id: str
    task_id: str | None = None
    source_draft_id: str | None = None
    version_number: int | None = Field(default=None, ge=1)
    document_type: DocumentType
    document_json: dict
    status: DocumentVersionStatus
    created_by: str | None = None
    approved_by: str | None = None
    approved_at: datetime | None = None
    created_at: datetime
    source_kind: DocumentSourceKind
    trust_method: DocumentTrustMethod
    source_system: str | None = None
    integration_principal: str | None = None
    external_tenant_id: str | None = None
    external_brand_id: str | None = None
    external_store_id: str | None = None
    external_supplier_id: str | None = None
    external_receiving_id: str | None = None
    external_version: int | None = Field(default=None, ge=1)
    record_status: UpstreamRecordStatus | None = None
    upstream_updated_at: datetime | None = None

    @model_validator(mode="after")
    def validate_source_shape(self) -> "DocumentVersion":
        """Reject mixed upload/upstream lineage and invalid trust combinations."""

        if self.source_kind == DocumentSourceKind.TAPTOUCH_RECEIVING:
            required = {
                "source_system": self.source_system,
                "integration_principal": self.integration_principal,
                "external_tenant_id": self.external_tenant_id,
                "external_store_id": self.external_store_id,
                "external_supplier_id": self.external_supplier_id,
                "external_receiving_id": self.external_receiving_id,
                "external_version": self.external_version,
                "record_status": self.record_status,
                "upstream_updated_at": self.upstream_updated_at,
            }
            missing = [
                name for name, value in required.items() if value is None or value == ""
            ]
            if missing:
                raise ValueError(f"Taptouch version missing: {', '.join(missing)}")
            if self.source_system != "taptouch":
                raise ValueError("Taptouch source_system must be 'taptouch'")
            if self.document_type != DocumentType.RECEIVE_NOTE:
                raise ValueError("Taptouch receiving must be a receive_note")
            if any(
                value is not None
                for value in (
                    self.task_id,
                    self.source_draft_id,
                    self.version_number,
                    self.created_by,
                    self.approved_by,
                )
            ):
                raise ValueError("Taptouch receiving cannot have upload or reviewer lineage")
            if (
                self.status != DocumentVersionStatus.APPROVED
                or self.trust_method != DocumentTrustMethod.UPSTREAM_AUTHORITATIVE
            ):
                raise ValueError(
                    "Taptouch receiving must be approved and upstream authoritative"
                )
            return self

        expected_source = (
            DocumentSourceKind.INVOICE_UPLOAD
            if self.document_type == DocumentType.INVOICE
            else DocumentSourceKind.EXTERNAL_RECEIVE_NOTE_UPLOAD
        )
        if self.source_kind != expected_source:
            raise ValueError("Upload source kind must match document type")
        if not all(
            value is not None
            for value in (
                self.task_id,
                self.source_draft_id,
                self.version_number,
                self.created_by,
            )
        ):
            raise ValueError("Uploaded versions require task, draft, version, and creator")
        if any(
            value is not None
            for value in (
                self.source_system,
                self.integration_principal,
                self.external_tenant_id,
                self.external_brand_id,
                self.external_store_id,
                self.external_supplier_id,
                self.external_receiving_id,
                self.external_version,
                self.record_status,
                self.upstream_updated_at,
            )
        ):
            raise ValueError("Uploaded versions cannot have upstream identity")
        expected_trust = (
            DocumentTrustMethod.HUMAN_APPROVED
            if self.status == DocumentVersionStatus.APPROVED
            else DocumentTrustMethod.UNTRUSTED
        )
        if self.trust_method != expected_trust:
            raise ValueError("Upload trust method must match review status")
        return self


class ReviewAction(BaseModel):
    """记录谁在何时对哪个版本执行了什么动作及原因。"""

    action_id: str
    version_id: str
    actor_user_id: str
    action: str
    field_path: str | None = None
    old_value: Any = None
    new_value: Any = None
    reason: str | None = None
    created_at: datetime
