from datetime import UTC, datetime

from app.api.dependencies import get_runtime_status_service
from app.domain.worker_runtime import WorkerHeartbeat
from app.main import app
from app.services.runtime_status_service import RuntimeStatusService
from tests.auth_helpers import reviewer_client


class RuntimeRepository:
    def latest(self) -> WorkerHeartbeat:
        now = datetime.now(UTC)
        return WorkerHeartbeat(
            worker_id="worker-a",
            version="0.1.0",
            started_at=now,
            last_seen_at=now,
        )


def test_runtime_status_is_authenticated_and_redacted() -> None:
    service = RuntimeStatusService(RuntimeRepository())
    previous = app.dependency_overrides.get(get_runtime_status_service)
    app.dependency_overrides[get_runtime_status_service] = lambda: service
    try:
        with reviewer_client(app) as client:
            response = client.get("/api/runtime/status")

        assert response.status_code == 200
        assert response.json()["worker"] == "online"
        assert set(response.json()) == {
            "api",
            "worker",
            "worker_last_seen_at",
            "worker_version",
        }
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_runtime_status_service, None)
        else:
            app.dependency_overrides[get_runtime_status_service] = previous
