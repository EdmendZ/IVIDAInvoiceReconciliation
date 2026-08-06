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


def test_backend_dockerfile_has_shared_non_root_api_and_worker_targets() -> None:
    dockerfile = _read("Dockerfile")

    assert "FROM python:3.12-slim AS builder" in dockerfile
    assert "uv sync --frozen --no-dev" in dockerfile
    assert "FROM runtime AS api" in dockerfile
    assert "FROM runtime AS worker" in dockerfile
    assert "USER ivida" in dockerfile
    assert 'CMD [".venv/bin/python", "-m", "uvicorn"' in dockerfile
    assert 'CMD [".venv/bin/python", "run_extraction_worker.py"]' in dockerfile


def test_docker_context_excludes_local_and_sensitive_files() -> None:
    ignored = _read(".dockerignore")

    for entry in (".git", ".env", ".venv", "frontend", "evaluation_data", "uploads"):
        assert entry in ignored


def test_frontend_image_builds_static_assets_and_proxies_api() -> None:
    dockerfile = _read("frontend/Dockerfile")
    nginx = _read("frontend/nginx.conf")

    assert "FROM node:22-alpine AS builder" in dockerfile
    assert "npm ci" in dockerfile
    assert "npm run typecheck" in dockerfile
    assert "npm run build" in dockerfile
    assert "COPY --from=builder /app/dist" in dockerfile
    assert "listen 8080" in nginx
    assert "try_files $uri $uri/ /index.html" in nginx
    assert "proxy_pass http://api:8200" in nginx
