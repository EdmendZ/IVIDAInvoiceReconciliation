from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_example_can_be_reconciled() -> None:
    example = client.get("/api/reconciliations/example").json()

    response = client.post("/api/reconciliations/compare", json=example)

    assert response.status_code == 200
    result = response.json()
    assert result["summary"] == {
        "total_lines": 1,
        "exact_lines": 1,
        "tolerance_lines": 0,
        "mismatch_lines": 0,
        "invoice_only_lines": 0,
        "receive_note_only_lines": 0,
        "requires_review": False,
    }

