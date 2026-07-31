"""批准版本门禁与核对结果持久化。

纯算法位于 reconciliation_service.py；本服务负责确认输入可信、类型正确，并
把参与版本 ID 与结果保存下来。
"""

from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from app.domain.document_versions import DocumentVersion
from app.domain.document_versions import DocumentVersionStatus
from app.domain.documents import DocumentType, Invoice, ReceiveNote
from app.domain.reconciliation import (
    ReconciliationRequest,
    ReconciliationTolerance,
)
from app.domain.reconciliation_candidates import ReconciliationCandidate
from app.domain.reconciliation_records import ReconciliationRecord
from app.services.candidate_matching_service import assess_candidate
from app.services.reconciliation_service import reconcile


class DocumentNotApproved(RuntimeError):
    pass


class ApprovedVersionReader(Protocol):
    def get_approved_version(self, version_id: str) -> DocumentVersion | None: ...

    def list_versions(
        self,
        *,
        status: DocumentVersionStatus | None = None,
    ) -> list[DocumentVersion]: ...


class ReconciliationWriter(Protocol):
    def create(self, record: ReconciliationRecord) -> ReconciliationRecord: ...


class ReconciliationApplicationService:
    """连接人工批准数据与确定性核对规则的应用服务。"""

    def __init__(
        self,
        *,
        review_repository: ApprovedVersionReader,
        reconciliation_repository: ReconciliationWriter,
    ) -> None:
        self._reviews = review_repository
        self._reconciliations = reconciliation_repository

    def list_candidates(
        self,
        approved_invoice_version_id: str,
    ) -> list[ReconciliationCandidate]:
        """为一张已批准 Invoice 对全部已批准 Receive Notes 排序。"""

        invoice_version = self._require_approved(
            approved_invoice_version_id,
            DocumentType.INVOICE,
        )
        invoice = Invoice.model_validate(invoice_version.document_json)
        candidates = [
            assess_candidate(
                invoice=invoice,
                receive_note=ReceiveNote.model_validate(version.document_json),
                receive_note_version_id=version.version_id,
            )
            for version in self._reviews.list_versions(
                status=DocumentVersionStatus.APPROVED
            )
            if version.document_type == DocumentType.RECEIVE_NOTE
        ]
        return sorted(
            candidates,
            key=lambda candidate: (
                -candidate.score,
                candidate.document_number,
            ),
        )

    def compare(
        self,
        approved_invoice_version_id: str,
        approved_receive_note_version_ids: list[str],
        *,
        created_by: str,
        tolerance: ReconciliationTolerance | None = None,
    ) -> ReconciliationRecord:
        """核对一个 Invoice Version 与一个或多个 Receive Note Versions。"""

        if not approved_receive_note_version_ids:
            raise ValueError("At least one Receive Note version is required")
        invoice_version = self._require_approved(
            approved_invoice_version_id,
            DocumentType.INVOICE,
        )
        note_versions = [
            self._require_approved(version_id, DocumentType.RECEIVE_NOTE)
            for version_id in approved_receive_note_version_ids
        ]
        # 在纯算法前重新构建 Pydantic 领域对象，避免数据库 JSON 绕过 Schema。
        result = reconcile(
            ReconciliationRequest(
                invoice=Invoice.model_validate(invoice_version.document_json),
                receive_notes=[
                    ReceiveNote.model_validate(version.document_json)
                    for version in note_versions
                ],
                tolerance=tolerance or ReconciliationTolerance(),
            )
        )
        return self._reconciliations.create(
            ReconciliationRecord(
                reconciliation_id=str(uuid4()),
                invoice_version_id=invoice_version.version_id,
                receive_note_version_ids=[
                    version.version_id for version in note_versions
                ],
                result=result,
                created_by=created_by,
                created_at=datetime.now(UTC),
            )
        )

    def _require_approved(
        self,
        version_id: str,
        expected_type: DocumentType,
    ) -> DocumentVersion:
        """同时校验批准状态和业务类型，阻止 Draft/误分类版本进入财务结果。"""

        version = self._reviews.get_approved_version(version_id)
        if version is None or version.document_type != expected_type:
            raise DocumentNotApproved(
                f"{expected_type.value} version is not approved"
            )
        return version
