from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.domain.document_sources import (
    DocumentSourceKind,
    DocumentTrustMethod,
    UpstreamRecordStatus,
)
from app.domain.document_versions import DocumentVersion, DocumentVersionStatus
from app.domain.documents import DocumentType


def _upload(**overrides) -> DocumentVersion:
    values = {
        "version_id": "version-1",
        "task_id": "task-1",
        "source_draft_id": "draft-1",
        "version_number": 1,
        "document_type": DocumentType.INVOICE,
        "document_json": {"document_type": "invoice"},
        "status": DocumentVersionStatus.DRAFT,
        "created_by": "user-1",
        "created_at": datetime.now(UTC),
        "source_kind": DocumentSourceKind.INVOICE_UPLOAD,
        "trust_method": DocumentTrustMethod.UNTRUSTED,
    }
    values.update(overrides)
    return DocumentVersion(**values)


def _taptouch(**overrides) -> DocumentVersion:
    now = datetime.now(UTC)
    values = {
        "version_id": "version-2",
        "document_type": DocumentType.RECEIVE_NOTE,
        "document_json": {"document_type": "receive_note"},
        "status": DocumentVersionStatus.APPROVED,
        "approved_at": now,
        "created_at": now,
        "source_kind": DocumentSourceKind.TAPTOUCH_RECEIVING,
        "trust_method": DocumentTrustMethod.UPSTREAM_AUTHORITATIVE,
        "source_system": "taptouch",
        "external_tenant_id": "tenant-1",
        "external_store_id": "store-1",
        "external_supplier_id": "supplier-1",
        "external_receiving_id": "receiving-1",
        "external_version": 1,
        "record_status": UpstreamRecordStatus.ACTIVE,
        "upstream_updated_at": now,
    }
    values.update(overrides)
    return DocumentVersion(**values)


def test_upload_requires_review_lineage() -> None:
    with pytest.raises(ValidationError, match="require task"):
        _upload(task_id=None)


def test_approved_upload_requires_human_trust() -> None:
    approved = _upload(
        status=DocumentVersionStatus.APPROVED,
        trust_method=DocumentTrustMethod.HUMAN_APPROVED,
    )
    assert approved.trust_method == DocumentTrustMethod.HUMAN_APPROVED
    with pytest.raises(ValidationError, match="trust method"):
        _upload(status=DocumentVersionStatus.APPROVED)


def test_upload_source_must_match_document_type() -> None:
    with pytest.raises(ValidationError, match="source kind"):
        _upload(document_type=DocumentType.RECEIVE_NOTE)


def test_taptouch_receiving_has_authoritative_shape() -> None:
    version = _taptouch()
    assert version.task_id is None
    assert version.approved_by is None
    assert version.record_status == UpstreamRecordStatus.ACTIVE


@pytest.mark.parametrize(
    "field",
    [
        "external_tenant_id",
        "external_store_id",
        "external_supplier_id",
        "external_receiving_id",
        "external_version",
        "record_status",
        "upstream_updated_at",
    ],
)
def test_taptouch_requires_external_identity(field: str) -> None:
    with pytest.raises(ValidationError, match="missing"):
        _taptouch(**{field: None})


def test_taptouch_rejects_upload_lineage() -> None:
    with pytest.raises(ValidationError, match="lineage"):
        _taptouch(task_id="fake-task")
