from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_ci_workflow_has_required_triggers_jobs_and_permissions() -> None:
    workflow = _read(".github/workflows/ci.yml")

    assert "pull_request:" in workflow
    assert "workflow_call:" in workflow
    assert "workflow_dispatch:" in workflow
    assert "contents: read" in workflow
    for job in ("quality:", "backend:", "postgres-integration:", "frontend:"):
        assert job in workflow
    assert "self-hosted" not in workflow


def test_ci_runs_real_postgres_and_frontend_verification() -> None:
    workflow = _read(".github/workflows/ci.yml")

    assert "postgres:18" in workflow
    assert "IVIDA_TEST_POSTGRES_URL" in workflow
    assert "alembic downgrade -1" in workflow
    assert "alembic check" in workflow
    assert "npm test -- --run" in workflow
    assert "npm run typecheck" in workflow
    assert "npm run build" in workflow
    assert "retention-days: 7" in workflow
