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
from app.domain.reconciliation_records import (
    ReconciliationPersistenceBundle,
    ReconciliationRecord,
)
from app.services.candidate_matching_service import assess_candidate
from app.services.reconciliation_case_factory import build_case_bundle
from app.services.reconciliation_service import reconcile


class DocumentNotApproved(RuntimeError):
    """输入版本未批准或业务类型与调用位置不一致。"""

    pass


class ReconciliationNotFound(LookupError):
    """请求的已持久化核对记录不存在。"""

    pass


class ApprovedVersionReader(Protocol):
    """对账用例只需要的批准版本只读视图。"""

    def get_approved_version(self, version_id: str) -> DocumentVersion | None: ...

    def list_versions(
        self,
        *,
        status: DocumentVersionStatus | None = None,
    ) -> list[DocumentVersion]: ...

    def list_reconciliation_versions(self) -> list[DocumentVersion]: ...


class ReconciliationRepository(Protocol):
    """保存并读取不可变核对结果的最小持久化端口。"""

    def create(
        self,
        bundle: ReconciliationPersistenceBundle,
    ) -> ReconciliationRecord: ...

    def get(self, reconciliation_id: str) -> ReconciliationRecord | None: ...


class ReconciliationApplicationService:
    """连接人工批准数据与确定性核对规则的应用服务。"""

    def __init__(
        self,
        *,
        review_repository: ApprovedVersionReader,
        reconciliation_repository: ReconciliationRepository,
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
                source_kind=version.source_kind,
                trust_method=version.trust_method,
                external_store_id=version.external_store_id,
                external_receiving_id=version.external_receiving_id,
                external_version=version.external_version,
                upstream_updated_at=version.upstream_updated_at,
            )
            for version in self._reviews.list_reconciliation_versions()
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
        now = datetime.now(UTC)
        record = ReconciliationRecord(
            reconciliation_id=str(uuid4()),
            invoice_version_id=invoice_version.version_id,
            receive_note_version_ids=[version.version_id for version in note_versions],
            result=result,
            created_by=created_by,
            created_at=now,
        )
        line_result_ids = [str(uuid4()) for _ in result.lines]
        case = build_case_bundle(record, line_result_ids, now=now)
        return self._reconciliations.create(
            ReconciliationPersistenceBundle(
                record=record,
                line_result_ids=line_result_ids,
                case=case,
            )
        )

    def get_record(self, reconciliation_id: str) -> ReconciliationRecord:
        """返回持久化快照；不存在时使用稳定业务异常而非泄漏仓储细节。"""

        record = self._reconciliations.get(reconciliation_id)
        if record is None:
            raise ReconciliationNotFound("Reconciliation not found")
        return record

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
