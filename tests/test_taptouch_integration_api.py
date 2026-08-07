from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.api.dependencies import get_taptouch_receiving_import_service
from app.core.config import Settings, get_settings
from app.domain.document_sources import (
    DocumentSourceKind,
    DocumentTrustMethod,
    UpstreamRecordStatus,
)
from app.domain.document_versions import DocumentVersion, DocumentVersionStatus
from app.domain.documents import DocumentType
from app.main import app
from app.services.taptouch_receiving_import_service import (
    ReceivingIdentityConflict,
    ReceivingImportOutcome,
    ReceivingVersionConflict,
)

NOW = datetime(2026, 8, 7, 4, 30, tzinfo=UTC)


def _version() -> DocumentVersion:
    return DocumentVersion(
        version_id="version-1",
        document_type=DocumentType.RECEIVE_NOTE,
        document_json={"document_type": "receive_note"},
        status=DocumentVersionStatus.APPROVED,
        approved_at=NOW,
        created_at=NOW,
        source_kind=DocumentSourceKind.TAPTOUCH_RECEIVING,
        trust_method=DocumentTrustMethod.UPSTREAM_AUTHORITATIVE,
        source_system="taptouch",
        external_tenant_id="tenant-1",
        external_store_id="store-1",
        external_supplier_id="supplier-1",
        external_receiving_id="receiving-1",
        external_version=1,
        record_status=UpstreamRecordStatus.ACTIVE,
        upstream_updated_at=NOW,
    )


PAYLOAD = {
    "external_tenant_id": "tenant-1",
    "external_store_id": "store-1",
    "external_supplier_id": "supplier-1",
    "external_receiving_id": "receiving-1",
    "external_version": 1,
    "record_status": "active",
    "document_number": "GRN-1",
    "received_at": "2026-08-07T04:30:00Z",
    "currency": "AUD",
    "supplier": {"name": "Fresh Foods"},
    "location": {"name": "Sydney"},
    "items": [{"description": "Cheese", "quantity": "2"}],
    "upstream_updated_at": "2026-08-07T04:31:00Z",
}


class Service:
    def __init__(self, result=None, error=None) -> None:
        self.result = result or ReceivingImportOutcome(version=_version(), created=True)
        self.error = error

    def import_record(self, payload):
        if self.error:
            raise self.error
        return self.result


def _client(service: Service, token: str = "secret") -> TestClient:
    app.dependency_overrides[get_settings] = lambda: Settings(
        taptouch_integration_token=token
    )
    app.dependency_overrides[get_taptouch_receiving_import_service] = lambda: service
    return TestClient(app)


def teardown_function() -> None:
    app.dependency_overrides.clear()


def test_authentication_is_required_and_disabled_when_unconfigured() -> None:
    client = _client(Service())
    assert client.post(
        "/api/integrations/taptouch/receiving-records", json=PAYLOAD
    ).status_code == 401
    client = _client(Service(), token="")
    assert client.post(
        "/api/integrations/taptouch/receiving-records",
        json=PAYLOAD,
        headers={"Authorization": "Bearer anything"},
    ).status_code == 401


def test_first_import_is_201_and_replay_is_200() -> None:
    client = _client(Service())
    headers = {"Authorization": "Bearer secret"}
    first = client.post(
        "/api/integrations/taptouch/receiving-records", json=PAYLOAD, headers=headers
    )
    assert first.status_code == 201
    assert first.json()["created"] is True

    replay = Service(ReceivingImportOutcome(version=_version(), created=False))
    app.dependency_overrides[get_taptouch_receiving_import_service] = lambda: replay
    response = client.post(
        "/api/integrations/taptouch/receiving-records", json=PAYLOAD, headers=headers
    )
    assert response.status_code == 200
    assert response.json()["version"]["version_id"] == "version-1"


def test_conflicts_have_stable_codes() -> None:
    headers = {"Authorization": "Bearer secret"}
    for error, code in (
        (ReceivingVersionConflict("old"), "stale_external_version"),
        (ReceivingIdentityConflict("changed"), "external_version_conflict"),
    ):
        response = _client(Service(error=error)).post(
            "/api/integrations/taptouch/receiving-records",
            json=PAYLOAD,
            headers=headers,
        )
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == code


def test_invalid_payload_is_422() -> None:
    invalid = dict(PAYLOAD)
    invalid["items"] = []
    response = _client(Service()).post(
        "/api/integrations/taptouch/receiving-records",
        json=invalid,
        headers={"Authorization": "Bearer secret"},
    )
    assert response.status_code == 422
