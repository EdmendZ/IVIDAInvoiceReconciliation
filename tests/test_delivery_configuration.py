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


def test_compose_orders_migration_before_runtime_services() -> None:
    compose = _read("compose.yaml")

    for service in ("postgres:", "minio:", "migrate:", "api:", "worker:", "frontend:"):
        assert service in compose
    assert "condition: service_healthy" in compose
    assert "condition: service_completed_successfully" in compose
    assert 'command: [".venv/bin/alembic", "upgrade", "head"]' in compose
    assert "MODEL_PROVIDER: disabled" in compose


def test_release_compose_uses_versioned_prebuilt_images() -> None:
    release = _read("compose.release.yaml")

    assert "${IVIDA_IMAGE_PREFIX}-api:${IVIDA_IMAGE_TAG}" in release
    assert "${IVIDA_IMAGE_PREFIX}-worker:${IVIDA_IMAGE_TAG}" in release
    assert "${IVIDA_IMAGE_PREFIX}-frontend:${IVIDA_IMAGE_TAG}" in release
    assert release.count("build: !reset null") == 4


def test_compose_template_contains_only_demo_credentials() -> None:
    template = _read(".env.compose.example")

    assert "CHANGE_ME" not in template
    assert "REMOTE_HOST=" not in template
    assert "SSH_PASSWORD=" not in template
    assert "MODEL_PROVIDER=disabled" in template
    assert "MINERU_API_TOKEN=disabled-local-demo" in template


def test_release_requires_ci_smoke_and_minimal_write_permissions() -> None:
    workflow = _read(".github/workflows/release.yml")

    assert "tags:" in workflow and "v*" in workflow
    assert "uses: ./.github/workflows/ci.yml" in workflow
    assert "contents: write" in workflow
    assert "packages: write" in workflow
    assert "docker compose" in workflow
    assert "tools/smoke_compose.py" in workflow
    assert "ghcr.io" in workflow
    assert "gh release create" in workflow
    assert ":latest" not in workflow
    assert "ssh" not in workflow.lower()


def test_release_records_commit_migration_and_digests() -> None:
    workflow = _read(".github/workflows/release.yml")

    assert "GITHUB_SHA" in workflow
    assert "alembic heads" in workflow
    assert "docker inspect" in workflow
    assert "release-manifest.md" in workflow


def test_dependabot_covers_all_delivery_ecosystems() -> None:
    config = _read(".github/dependabot.yml")

    for ecosystem in ('"pip"', '"npm"', '"docker"', '"github-actions"'):
        assert f"package-ecosystem: {ecosystem}" in config
    assert "interval: weekly" in config
    assert "open-pull-requests-limit" in config


def test_codeql_scans_python_and_typescript_without_write_all() -> None:
    workflow = _read(".github/workflows/codeql.yml")

    assert "python" in workflow
    assert "javascript-typescript" in workflow
    assert "security-events: write" in workflow
    assert "contents: read" in workflow
    assert "write-all" not in workflow
