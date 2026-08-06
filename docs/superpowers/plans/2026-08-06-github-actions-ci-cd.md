# GitHub Actions CI/CD Showcase Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为公开 GitHub 仓库增加可重复、无付费外部依赖的 CI、容器化演示环境、GHCR 镜像发布和 GitHub Release 流程。

**Architecture:** Pull Request 和 `main` 使用可复用 `ci.yml` 并行运行质量、后端、真实 PostgreSQL 和前端检查；Tag 发布先复用同一 CI，再构建 API、Worker、Frontend 镜像，在临时 Compose 栈中执行 Smoke Test，最后推送 GHCR 并生成 Release。所有自动化使用 GitHub-hosted Ubuntu Runner、临时凭据和临时服务，不连接现有服务器或付费 Provider。

**Tech Stack:** GitHub Actions, Python 3.12, uv 0.11.26, Node.js 22, PostgreSQL 18, Docker BuildKit, Docker Compose, GHCR, CodeQL, Dependabot, Trivy, FastAPI, React/Vite, pytest, Vitest, Alembic.

## Global Constraints

- 只使用 GitHub-hosted Ubuntu Runner；不得配置 self-hosted Runner。
- Workflow、脚本和文档不得包含真实服务器地址、SSH 凭据、数据库密码、MinIO 密钥、MinerU Token 或模型 API Key。
- PR 和 Release 验证不得调用真实 MinerU、OpenAI-compatible Provider 或其他付费服务。
- Python 版本保持项目约束 `>=3.11,<3.13`，CI 和镜像统一使用 Python 3.12。
- Node CI 和前端构建镜像统一使用 Node.js 22。
- PostgreSQL 集成测试统一使用 PostgreSQL 18 Service Container 和一次性数据库。
- API、Worker、Frontend 分别产出镜像；API 和 Worker 必须复用同一后端依赖层。
- 数据库迁移由一次性 `migrate` 服务执行；API 和 Worker 不自行执行 Alembic。
- Release 不自动 downgrade 数据库，也不覆盖语义不明确的 `latest` 标签。
- 所有新增行为先写失败测试或失败的配置契约检查，再写最小实现。
- 本计划不部署到现有服务器，不增加 Kubernetes、Helm、Terraform、VPN 或真实生产配置。

---

## File and Responsibility Map

### New delivery files

- `.github/workflows/ci.yml`: PR、`main` 和可复用 CI 入口。
- `.github/workflows/release.yml`: Tag/手动预发布、镜像验证、GHCR 和 Release。
- `.github/workflows/codeql.yml`: Python 与 JavaScript/TypeScript 静态安全扫描。
- `.github/dependabot.yml`: Python、npm、Docker、GitHub Actions 依赖更新。
- `Dockerfile`: 共用后端构建层及 `api`、`worker` Targets。
- `frontend/Dockerfile`: Vite 构建和 Nginx 静态运行镜像。
- `frontend/nginx.conf`: SPA fallback 和 `/api` 反向代理。
- `.dockerignore`: 后端构建上下文排除规则。
- `frontend/.dockerignore`: 前端构建上下文排除规则。
- `compose.yaml`: 本地完整演示栈和本机构建入口。
- `compose.release.yaml`: 使用 GHCR/本地预构建镜像的发布覆盖配置。
- `.env.compose.example`: 无真实 Secret 的 Compose 环境模板。
- `tools/smoke_compose.py`: 对容器栈执行确定性 HTTP 和 Migration Smoke Test。
- `tests/test_delivery_configuration.py`: Workflow、容器、Compose 和发布契约守护。
- `docs/operations/20-ci-cd-and-release.md`: CI、镜像、Release、回滚和故障排查 Runbook。

### Existing files to update

- `.gitignore`: 忽略本地 `.env.compose` 和 Smoke 输出，不忽略模板。
- `README.md:139-158`: 增加 CI/CD、Compose 和 Release 快速入口。
- `docs/code-document-map.json`: 将交付文件映射到 CI/CD Runbook 和 README。
- `docs/operations/08-api-ui-and-local-run.md`: 链接容器演示入口，不复制完整 Runbook。

---

### Task 1: Add Reusable Pull Request and Main-Branch CI

**Files:**
- Create: `.github/workflows/ci.yml`
- Create: `tests/test_delivery_configuration.py`
- Modify: `.gitignore`
- Test: `tests/test_delivery_configuration.py`

**Interfaces:**
- Consumes: `uv.lock`, `frontend/package-lock.json`, `tools/check_documentation_sync.py`, `tests/test_postgres_reconciliation_case_integration.py`, `alembic.ini`.
- Produces: reusable workflow callable as `uses: ./.github/workflows/ci.yml`; required Job IDs `quality`, `backend`, `postgres-integration`, `frontend`.

- [ ] **Step 1: Write failing CI contract tests**

Add this initial content to `tests/test_delivery_configuration.py`:

```python
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
```

- [ ] **Step 2: Run the CI contract tests to verify RED**

Run:

```powershell
uv run pytest tests/test_delivery_configuration.py -q
```

Expected: both tests fail with `FileNotFoundError` for `.github/workflows/ci.yml`.

- [ ] **Step 3: Create the reusable CI workflow**

Create `.github/workflows/ci.yml` with these exact structural elements:

```yaml
name: CI

on:
  pull_request:
  push:
    branches: [main]
  workflow_dispatch:
  workflow_call:

permissions:
  contents: read

concurrency:
  group: ci-${{ github.workflow }}-${{ github.event.pull_request.number || github.ref }}
  cancel-in-progress: true

env:
  PYTHON_VERSION: "3.12"
  NODE_VERSION: "22"
  UV_VERSION: "0.11.26"

jobs:
  quality:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
        with:
          fetch-depth: 0
      - uses: actions/setup-python@v6
        with:
          python-version: ${{ env.PYTHON_VERSION }}
      - uses: astral-sh/setup-uv@v7
        with:
          version: ${{ env.UV_VERSION }}
          enable-cache: true
      - run: uv sync --locked --all-groups
      - run: uv run python -m compileall -q app tests tools
      - name: Resolve comparison base
        id: base
        shell: bash
        run: |
          base="${{ github.event.pull_request.base.sha || github.event.before }}"
          if [[ -z "$base" || "$base" =~ ^0+$ ]]; then base="HEAD~1"; fi
          echo "sha=$base" >> "$GITHUB_OUTPUT"
      - run: uv run python tools/check_documentation_sync.py --base-ref "${{ steps.base.outputs.sha }}"
      - run: git diff --check "${{ steps.base.outputs.sha }}"...HEAD

  backend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - uses: actions/setup-python@v6
        with:
          python-version: ${{ env.PYTHON_VERSION }}
      - uses: astral-sh/setup-uv@v7
        with:
          version: ${{ env.UV_VERSION }}
          enable-cache: true
      - run: uv sync --locked --all-groups
      - run: uv run pytest --ignore=tests/test_postgres_reconciliation_case_integration.py --junitxml=backend-junit.xml
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: backend-junit
          path: backend-junit.xml
          retention-days: 7

  postgres-integration:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:18
        env:
          POSTGRES_USER: ivida_ci
          POSTGRES_PASSWORD: ci-only-password
          POSTGRES_DB: ivida_ci
        ports:
          - 5432:5432
        options: >-
          --health-cmd "pg_isready -U ivida_ci -d ivida_ci"
          --health-interval 5s
          --health-timeout 5s
          --health-retries 12
    env:
      DATABASE_URL: postgresql+psycopg://ivida_ci:ci-only-password@127.0.0.1:5432/ivida_ci
      IVIDA_TEST_POSTGRES_URL: postgresql+psycopg://ivida_ci:ci-only-password@127.0.0.1:5432/ivida_ci
      APP_ENV: test
    steps:
      - uses: actions/checkout@v6
      - uses: actions/setup-python@v6
        with:
          python-version: ${{ env.PYTHON_VERSION }}
      - uses: astral-sh/setup-uv@v7
        with:
          version: ${{ env.UV_VERSION }}
          enable-cache: true
      - run: uv sync --locked --all-groups
      - run: uv run alembic upgrade head
      - run: uv run pytest tests/test_postgres_reconciliation_case_integration.py --junitxml=postgres-junit.xml
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: postgres-junit
          path: postgres-junit.xml
          retention-days: 7
      - run: uv run alembic downgrade -1
      - run: uv run alembic upgrade head
      - run: uv run alembic current
      - run: uv run alembic heads
      - run: uv run alembic check

  frontend:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: frontend
    steps:
      - uses: actions/checkout@v6
      - uses: actions/setup-node@v6
        with:
          node-version: ${{ env.NODE_VERSION }}
          cache: npm
          cache-dependency-path: frontend/package-lock.json
      - run: npm ci
      - run: npm test -- --run
      - run: npm run typecheck
      - run: npm run build
```

During implementation, preserve the Job IDs, Action versions and commands exactly. A version change requires an explicit plan correction before implementation continues.

Append `*-junit.xml` to `.gitignore` so a local reproduction of the CI commands does
not leave report files in Git status.

- [ ] **Step 4: Run focused and existing suites**

Run:

```powershell
uv run pytest tests/test_delivery_configuration.py tests/test_documentation_sync.py -q
```

Expected: all tests pass.

Then run:

```powershell
uv run pytest --ignore=tests/test_postgres_reconciliation_case_integration.py
cd frontend
npm test -- --run
npm run typecheck
npm run build
```

Expected: backend and frontend suites pass without contacting external services.

- [ ] **Step 5: Commit Task 1**

```powershell
git add .github/workflows/ci.yml tests/test_delivery_configuration.py .gitignore
git commit -m "ci: add reusable pull request checks"
```

---

### Task 2: Build Non-Root API and Worker Images

**Files:**
- Create: `Dockerfile`
- Create: `.dockerignore`
- Modify: `tests/test_delivery_configuration.py`
- Test: `tests/test_delivery_configuration.py`

**Interfaces:**
- Consumes: `run_api.py`, `run_extraction_worker.py`, `pyproject.toml`, `uv.lock`, `alembic.ini`, `migrations/**`.
- Produces: Docker Targets `api` and `worker`; both contain `/app/.venv`, application code and migrations; API listens on `8200`.

- [ ] **Step 1: Add failing backend image contract tests**

Append:

```python
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
```

- [ ] **Step 2: Run RED verification**

```powershell
uv run pytest tests/test_delivery_configuration.py -q
```

Expected: new tests fail because `Dockerfile` and `.dockerignore` do not exist.

- [ ] **Step 3: Create the shared backend Dockerfile**

Create `Dockerfile`:

```dockerfile
# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:0.11.26 /uv /uvx /bin/
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY app ./app
COPY migrations ./migrations
COPY alembic.ini run_api.py run_extraction_worker.py ./
RUN uv sync --frozen --no-dev

FROM python:3.12-slim AS runtime
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
RUN groupadd --system ivida && useradd --system --gid ivida --home /app ivida
WORKDIR /app
COPY --from=builder --chown=ivida:ivida /app /app
USER ivida
EXPOSE 8200

FROM runtime AS api
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=5 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8200/api/health', timeout=2)"]
CMD [".venv/bin/python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8200"]

FROM runtime AS worker
CMD [".venv/bin/python", "run_extraction_worker.py"]
```

Create `.dockerignore` with explicit exclusions:

```text
.git
.github
.idea
.vscode
.env
.env.*
!.env.example
.venv
.pytest_cache
__pycache__
*.pyc
*.log
frontend
evaluation_data
uploads
logs
.local-demo
.worktrees
htmlcov
coverage.xml
```

- [ ] **Step 4: Verify image contracts and build both targets**

```powershell
uv run pytest tests/test_delivery_configuration.py -q
docker build --target api -t ivida-api:test .
docker build --target worker -t ivida-worker:test .
```

Expected: tests and both builds pass.

- [ ] **Step 5: Smoke the API image without external services**

```powershell
docker run --rm -d --name ivida-api-smoke -p 18200:8200 -e APP_ENV=dev ivida-api:test
```

Wait until healthy, then run:

```powershell
Invoke-RestMethod http://127.0.0.1:18200/api/health
docker stop ivida-api-smoke
```

Expected: response contains `status=ok`, and the container stops cleanly.

- [ ] **Step 6: Commit Task 2**

```powershell
git add Dockerfile .dockerignore tests/test_delivery_configuration.py
git commit -m "build: containerize API and worker"
```

---

### Task 3: Build the Frontend Runtime Image

**Files:**
- Create: `frontend/Dockerfile`
- Create: `frontend/.dockerignore`
- Create: `frontend/nginx.conf`
- Modify: `tests/test_delivery_configuration.py`
- Test: `tests/test_delivery_configuration.py`

**Interfaces:**
- Consumes: relative `/api` calls in `frontend/src/api/client.ts`, `frontend/package-lock.json`, Vite SPA output.
- Produces: `ivida-frontend` image listening on port `8080`, with SPA fallback and `/api/` proxy to `http://api:8200`.

- [ ] **Step 1: Add failing frontend container tests**

Append:

```python
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
```

- [ ] **Step 2: Run RED verification**

```powershell
uv run pytest tests/test_delivery_configuration.py -q
```

Expected: the frontend image test fails with missing files.

- [ ] **Step 3: Create the frontend build and Nginx configuration**

Create `frontend/Dockerfile`:

```dockerfile
# syntax=docker/dockerfile:1.7
FROM node:22-alpine AS builder
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run typecheck && npm run build

FROM nginxinc/nginx-unprivileged:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
  CMD ["wget", "-q", "--spider", "http://127.0.0.1:8080/"]
```

Create `frontend/nginx.conf`:

```nginx
server {
    listen 8080;
    server_name _;
    root /usr/share/nginx/html;
    index index.html;

    location /api/ {
        proxy_pass http://api:8200;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

Create `frontend/.dockerignore`:

```text
node_modules
dist
tsconfig.tsbuildinfo
*.log
.env
.env.*
```

- [ ] **Step 4: Run contracts, frontend tests and image build**

```powershell
uv run pytest tests/test_delivery_configuration.py -q
cd frontend
npm test -- --run
npm run typecheck
npm run build
docker build -t ivida-frontend:test .
```

Expected: all commands pass.

- [ ] **Step 5: Commit Task 3**

```powershell
git add frontend/Dockerfile frontend/.dockerignore frontend/nginx.conf tests/test_delivery_configuration.py
git commit -m "build: containerize review frontend"
```

---

### Task 4: Add the Reproducible Compose Demo and Smoke Test

**Files:**
- Create: `compose.yaml`
- Create: `compose.release.yaml`
- Create: `.env.compose.example`
- Create: `tools/smoke_compose.py`
- Modify: `.gitignore`
- Modify: `tests/test_delivery_configuration.py`
- Test: `tests/test_delivery_configuration.py`

**Interfaces:**
- Consumes: images/Targets from Tasks 2–3, `/api/health`, PostgreSQL 18, MinIO health endpoint, Alembic.
- Produces: `docker compose up --build` demo stack; `python tools/smoke_compose.py --base-url http://127.0.0.1:5274`; release override driven by `IVIDA_IMAGE_PREFIX` and `IVIDA_IMAGE_TAG`.

- [ ] **Step 1: Add failing Compose and Smoke contract tests**

Append:

```python
def test_compose_orders_migration_before_runtime_services() -> None:
    compose = _read("compose.yaml")

    for service in ("postgres:", "minio:", "migrate:", "api:", "worker:", "frontend:"):
        assert service in compose
    assert "condition: service_healthy" in compose
    assert "condition: service_completed_successfully" in compose
    assert "alembic upgrade head" in compose
    assert "MODEL_PROVIDER: disabled" in compose


def test_release_compose_uses_versioned_prebuilt_images() -> None:
    release = _read("compose.release.yaml")

    assert "${IVIDA_IMAGE_PREFIX}-api:${IVIDA_IMAGE_TAG}" in release
    assert "${IVIDA_IMAGE_PREFIX}-worker:${IVIDA_IMAGE_TAG}" in release
    assert "${IVIDA_IMAGE_PREFIX}-frontend:${IVIDA_IMAGE_TAG}" in release


def test_compose_template_contains_only_demo_credentials() -> None:
    template = _read(".env.compose.example")

    assert "CHANGE_ME" not in template
    assert "REMOTE_HOST=" not in template
    assert "SSH_PASSWORD=" not in template
    assert "MODEL_PROVIDER=disabled" in template
    assert "MINERU_API_TOKEN=disabled-local-demo" in template
```

- [ ] **Step 2: Run RED verification**

```powershell
uv run pytest tests/test_delivery_configuration.py -q
```

Expected: missing Compose, environment template and Smoke files cause failures.

- [ ] **Step 3: Create the Compose environment template**

Create `.env.compose.example`:

```dotenv
APP_ENV=demo
POSTGRES_DB=ivida_demo
POSTGRES_USER=ivida_demo
POSTGRES_PASSWORD=ivida-demo-only
MINIO_ROOT_USER=ivida-demo
MINIO_ROOT_PASSWORD=ivida-demo-only
MINIO_BUCKET_NAME=ivida-invoice-documents
MODEL_PROVIDER=disabled
MINERU_API_TOKEN=disabled-local-demo
NORMALIZATION_API_KEY=disabled-local-demo
NORMALIZATION_MODEL=disabled-local-demo
IVIDA_IMAGE_PREFIX=ivida
IVIDA_IMAGE_TAG=dev
```

Add `.env.compose` to `.gitignore`. Users copy the template to `.env.compose`; the template remains tracked.

- [ ] **Step 4: Create the local Compose stack**

Create `compose.yaml` with this dependency and configuration model:

```yaml
name: ivida-invoice-reconciliation

services:
  postgres:
    image: postgres:18
    environment:
      POSTGRES_DB: ${POSTGRES_DB:-ivida_demo}
      POSTGRES_USER: ${POSTGRES_USER:-ivida_demo}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-ivida-demo-only}
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-ivida_demo} -d ${POSTGRES_DB:-ivida_demo}"]
      interval: 5s
      timeout: 5s
      retries: 12
    volumes:
      - postgres-data:/var/lib/postgresql

  minio:
    image: minio/minio:RELEASE.2024-12-18T13-15-44Z
    command: server /data --console-address :9001
    environment:
      MINIO_ROOT_USER: ${MINIO_ROOT_USER:-ivida-demo}
      MINIO_ROOT_PASSWORD: ${MINIO_ROOT_PASSWORD:-ivida-demo-only}
    healthcheck:
      test: ["CMD", "curl", "-f", "http://127.0.0.1:9000/minio/health/live"]
      interval: 5s
      timeout: 5s
      retries: 12
    volumes:
      - minio-data:/data

  migrate:
    build:
      context: .
      target: api
    command: [".venv/bin/alembic", "upgrade", "head"]
    environment: &backend-env
      APP_ENV: ${APP_ENV:-demo}
      DATABASE_URL: postgresql+psycopg://${POSTGRES_USER:-ivida_demo}:${POSTGRES_PASSWORD:-ivida-demo-only}@postgres:5432/${POSTGRES_DB:-ivida_demo}
      MINIO_ENDPOINT: minio:9000
      MINIO_ACCESS_KEY: ${MINIO_ROOT_USER:-ivida-demo}
      MINIO_SECRET_KEY: ${MINIO_ROOT_PASSWORD:-ivida-demo-only}
      MINIO_BUCKET_NAME: ${MINIO_BUCKET_NAME:-ivida-invoice-documents}
      MINIO_SECURE: "false"
      MODEL_PROVIDER: disabled
      MINERU_API_TOKEN: ${MINERU_API_TOKEN:-disabled-local-demo}
      NORMALIZATION_API_KEY: ${NORMALIZATION_API_KEY:-disabled-local-demo}
      NORMALIZATION_MODEL: ${NORMALIZATION_MODEL:-disabled-local-demo}
    depends_on:
      postgres:
        condition: service_healthy

  api:
    build:
      context: .
      target: api
    environment: *backend-env
    depends_on:
      migrate:
        condition: service_completed_successfully
      minio:
        condition: service_healthy
    ports:
      - "8200:8200"

  worker:
    build:
      context: .
      target: worker
    environment: *backend-env
    depends_on:
      migrate:
        condition: service_completed_successfully
      minio:
        condition: service_healthy

  frontend:
    build:
      context: frontend
    depends_on:
      api:
        condition: service_healthy
    ports:
      - "5274:8080"

volumes:
  postgres-data:
  minio-data:
```

Create `compose.release.yaml`:

```yaml
services:
  migrate:
    image: ${IVIDA_IMAGE_PREFIX}-api:${IVIDA_IMAGE_TAG}
    build: null
  api:
    image: ${IVIDA_IMAGE_PREFIX}-api:${IVIDA_IMAGE_TAG}
    build: null
  worker:
    image: ${IVIDA_IMAGE_PREFIX}-worker:${IVIDA_IMAGE_TAG}
    build: null
  frontend:
    image: ${IVIDA_IMAGE_PREFIX}-frontend:${IVIDA_IMAGE_TAG}
    build: null
```

- [ ] **Step 5: Implement deterministic Compose Smoke checks**

Create `tools/smoke_compose.py` using only the Python standard library plus the project's SQLAlchemy/Alembic dependencies:

```python
from __future__ import annotations

import argparse
import json
import time
import urllib.request


def wait_json(url: str, timeout_seconds: int = 60) -> dict:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            last_error = exc
            time.sleep(1)
    raise RuntimeError(f"Timed out waiting for {url}: {last_error}")


def wait_text(url: str, timeout_seconds: int = 60) -> str:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                return response.read().decode("utf-8")
        except Exception as exc:
            last_error = exc
            time.sleep(1)
    raise RuntimeError(f"Timed out waiting for {url}: {last_error}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", default="http://127.0.0.1:8200")
    parser.add_argument("--frontend-url", default="http://127.0.0.1:5274")
    args = parser.parse_args()

    health = wait_json(f"{args.api_url}/api/health")
    if health.get("status") != "ok":
        raise RuntimeError(f"Unexpected API health response: {health}")
    html = wait_text(args.frontend_url)
    if '<div id="root">' not in html:
        raise RuntimeError("Frontend root element is missing")
    print("Compose smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 6: Run the complete local container acceptance**

```powershell
Copy-Item .env.compose.example .env.compose
docker compose --env-file .env.compose up --build -d
uv run python tools/smoke_compose.py
docker compose --env-file .env.compose exec -T api .venv/bin/alembic current
docker compose --env-file .env.compose down -v
```

Expected: all six services reach their intended state, Smoke passes, Alembic reports the single head, and volumes are removed. If any command fails, collect `docker compose logs --no-color` before cleanup.

- [ ] **Step 7: Commit Task 4**

```powershell
git add compose.yaml compose.release.yaml .env.compose.example .gitignore tools/smoke_compose.py tests/test_delivery_configuration.py
git commit -m "build: add reproducible Compose demo"
```

---

### Task 5: Publish Tested Images and GitHub Releases

**Files:**
- Create: `.github/workflows/release.yml`
- Modify: `tests/test_delivery_configuration.py`
- Test: `tests/test_delivery_configuration.py`

**Interfaces:**
- Consumes: reusable CI from Task 1, Docker images and Compose files from Tasks 2–4, `tools/smoke_compose.py`.
- Produces: GHCR repositories suffixed `-api`, `-worker`, `-frontend`; version and SHA tags; release manifest containing Commit, Alembic revision and image Digests.

- [ ] **Step 1: Add failing Release contract tests**

Append:

```python
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
    assert "latest" not in workflow
    assert "ssh" not in workflow.lower()


def test_release_records_commit_migration_and_digests() -> None:
    workflow = _read(".github/workflows/release.yml")

    assert "GITHUB_SHA" in workflow
    assert "alembic heads" in workflow
    assert "docker inspect" in workflow
    assert "release-manifest.md" in workflow
```

- [ ] **Step 2: Run RED verification**

```powershell
uv run pytest tests/test_delivery_configuration.py -q
```

Expected: Release tests fail because `.github/workflows/release.yml` is missing.

- [ ] **Step 3: Create the Release workflow skeleton and validation gate**

Create `.github/workflows/release.yml` with:

```yaml
name: Release

on:
  push:
    tags: ["v*"]
  workflow_dispatch:
    inputs:
      version:
        description: Pre-release version such as v0.2.0-rc.1
        required: true

permissions:
  contents: read

jobs:
  verify:
    uses: ./.github/workflows/ci.yml

  release:
    needs: verify
    runs-on: ubuntu-latest
    permissions:
      contents: write
      packages: write
    env:
      VERSION: ${{ github.event.inputs.version || github.ref_name }}
    steps:
      - uses: actions/checkout@v6
      - name: Validate version
        shell: bash
        run: |
          [[ "$VERSION" =~ ^v[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$ ]]
      - name: Resolve lowercase image prefix
        id: image
        shell: bash
        run: echo "prefix=ghcr.io/${GITHUB_REPOSITORY,,}" >> "$GITHUB_OUTPUT"
```

- [ ] **Step 4: Add build, local smoke and scan before registry login**

Continue the same `release` Job with shell steps that build local immutable candidates:

```yaml
      - name: Build local release candidates
        shell: bash
        run: |
          short_sha="${GITHUB_SHA::7}"
          docker build --target api -t "${{ steps.image.outputs.prefix }}-api:sha-$short_sha" .
          docker build --target worker -t "${{ steps.image.outputs.prefix }}-worker:sha-$short_sha" .
          docker build -t "${{ steps.image.outputs.prefix }}-frontend:sha-$short_sha" frontend
      - name: Smoke local release candidates
        shell: bash
        env:
          IVIDA_IMAGE_PREFIX: ${{ steps.image.outputs.prefix }}
        run: |
          export IVIDA_IMAGE_TAG="sha-${GITHUB_SHA::7}"
          cp .env.compose.example .env.compose
          docker compose --env-file .env.compose -f compose.yaml -f compose.release.yaml up -d
          cleanup() { docker compose --env-file .env.compose -f compose.yaml -f compose.release.yaml down -v; }
          trap cleanup EXIT
          uv run python tools/smoke_compose.py
          docker compose --env-file .env.compose -f compose.yaml -f compose.release.yaml exec -T api .venv/bin/alembic current
```

Add Python/uv setup before the Smoke step:

```yaml
      - uses: actions/setup-python@v6
        with:
          python-version: "3.12"
      - uses: astral-sh/setup-uv@v7
        with:
          version: "0.11.26"
          enable-cache: true
      - run: uv sync --locked --all-groups
```

After local Smoke succeeds, scan each candidate using the immutable commit behind
Trivy Action `v0.36.0`:

```yaml
      - name: Scan API image
        uses: aquasecurity/trivy-action@a9c7b0f06e461e9d4b4d1711f154ee024b8d7ab8
        with:
          image-ref: ${{ steps.image.outputs.prefix }}-api:sha-${{ env.SHORT_SHA }}
          format: table
          severity: CRITICAL,HIGH
          exit-code: "1"
      - name: Scan Worker image
        uses: aquasecurity/trivy-action@a9c7b0f06e461e9d4b4d1711f154ee024b8d7ab8
        with:
          image-ref: ${{ steps.image.outputs.prefix }}-worker:sha-${{ env.SHORT_SHA }}
          format: table
          severity: CRITICAL,HIGH
          exit-code: "1"
      - name: Scan Frontend image
        uses: aquasecurity/trivy-action@a9c7b0f06e461e9d4b4d1711f154ee024b8d7ab8
        with:
          image-ref: ${{ steps.image.outputs.prefix }}-frontend:sha-${{ env.SHORT_SHA }}
          format: table
          severity: CRITICAL,HIGH
          exit-code: "1"
```

Set `SHORT_SHA` in `$GITHUB_ENV` during the image-prefix step so the build, Smoke,
scan and push steps use the same immutable tag:

```bash
echo "SHORT_SHA=${GITHUB_SHA::7}" >> "$GITHUB_ENV"
```

- [ ] **Step 5: Log in only after Smoke passes, push tags and create a manifest**

Add:

```yaml
      - uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - name: Push version and SHA tags
        shell: bash
        run: |
          short_sha="${GITHUB_SHA::7}"
          for service in api worker frontend; do
            image="${{ steps.image.outputs.prefix }}-$service"
            docker tag "$image:sha-$short_sha" "$image:$VERSION"
            docker push "$image:sha-$short_sha"
            docker push "$image:$VERSION"
          done
      - name: Write release manifest
        shell: bash
        run: |
          {
            echo "# IVIDA $VERSION"
            echo
            echo "- Commit: \`$GITHUB_SHA\`"
            echo "- Alembic: \`$(uv run alembic heads | tr -d '\r')\`"
            for service in api worker frontend; do
              image="${{ steps.image.outputs.prefix }}-$service:$VERSION"
              docker pull "$image" >/dev/null
              echo "- $service: \`$(docker inspect --format='{{index .RepoDigests 0}}' "$image")\`"
            done
          } > release-manifest.md
      - name: Create GitHub Release
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        shell: bash
        run: |
          if [[ "$GITHUB_EVENT_NAME" == "workflow_dispatch" ]]; then
            gh release create "$VERSION" release-manifest.md compose.release.yaml \
              --notes-file release-manifest.md --prerelease --target "$GITHUB_SHA"
          else
            gh release create "$VERSION" release-manifest.md compose.release.yaml \
              --notes-file release-manifest.md --target "$GITHUB_SHA"
          fi
```

This exact branch makes `workflow_dispatch` releases pre-releases and Tag-triggered
semantic versions normal Releases. Do not create or push `latest`.

- [ ] **Step 6: Run focused tests and validate Workflow syntax**

```powershell
uv run pytest tests/test_delivery_configuration.py -q
git diff --check
```

Then push the feature branch and use a temporary `v0.0.0-ci.1` pre-release Tag only after PR CI is green. Verify all three GHCR packages, Digests and Release assets exist; delete the temporary Tag/Release/Packages only if the repository owner explicitly approves cleanup.

- [ ] **Step 7: Commit Task 5**

```powershell
git add .github/workflows/release.yml tests/test_delivery_configuration.py
git commit -m "ci: publish tested release images"
```

---

### Task 6: Add Dependency and Static Security Automation

**Files:**
- Create: `.github/dependabot.yml`
- Create: `.github/workflows/codeql.yml`
- Modify: `tests/test_delivery_configuration.py`
- Test: `tests/test_delivery_configuration.py`

**Interfaces:**
- Consumes: public repository, Python root, npm project in `/frontend`, root/frontend Dockerfiles, GitHub Actions workflows.
- Produces: weekly grouped dependency PRs and CodeQL scans for `python` and `javascript-typescript`.

- [ ] **Step 1: Add failing security automation contracts**

Append:

```python
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
```

- [ ] **Step 2: Run RED verification**

```powershell
uv run pytest tests/test_delivery_configuration.py -q
```

Expected: new tests fail because the Dependabot and CodeQL files are absent.

- [ ] **Step 3: Add weekly Dependabot updates**

Create `.github/dependabot.yml`:

```yaml
version: 2
updates:
  - package-ecosystem: "pip"
    directory: "/"
    schedule: { interval: weekly }
    open-pull-requests-limit: 5
    groups:
      python-minor-patch:
        update-types: [minor, patch]
  - package-ecosystem: "npm"
    directory: "/frontend"
    schedule: { interval: weekly }
    open-pull-requests-limit: 5
    groups:
      frontend-minor-patch:
        update-types: [minor, patch]
  - package-ecosystem: "docker"
    directory: "/"
    schedule: { interval: weekly }
    open-pull-requests-limit: 3
  - package-ecosystem: "docker"
    directory: "/frontend"
    schedule: { interval: weekly }
    open-pull-requests-limit: 3
  - package-ecosystem: "github-actions"
    directory: "/"
    schedule: { interval: weekly }
    open-pull-requests-limit: 3
```

- [ ] **Step 4: Add CodeQL with minimum permissions**

Create `.github/workflows/codeql.yml`:

```yaml
name: CodeQL

on:
  pull_request:
  push:
    branches: [main]
  schedule:
    - cron: "23 3 * * 1"

permissions:
  contents: read
  security-events: write

jobs:
  analyze:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        language: [python, javascript-typescript]
    steps:
      - uses: actions/checkout@v6
      - uses: github/codeql-action/init@v4
        with:
          languages: ${{ matrix.language }}
      - uses: github/codeql-action/analyze@v4
```

- [ ] **Step 5: Verify and commit Task 6**

```powershell
uv run pytest tests/test_delivery_configuration.py -q
git diff --check
git add .github/dependabot.yml .github/workflows/codeql.yml tests/test_delivery_configuration.py
git commit -m "ci: add dependency and security automation"
```

---

### Task 7: Document CI/CD, Release, Rollback, and Repository Settings

**Files:**
- Create: `docs/operations/20-ci-cd-and-release.md`
- Modify: `README.md:139-158`
- Modify: `docs/operations/08-api-ui-and-local-run.md`
- Modify: `docs/code-document-map.json`
- Modify: `tests/test_reference_documentation.py`
- Modify: `tests/test_delivery_configuration.py`
- Test: `tests/test_reference_documentation.py`
- Test: `tests/test_delivery_configuration.py`

**Interfaces:**
- Consumes: all delivery commands and files from Tasks 1–6.
- Produces: one authoritative Runbook, concise README entry, documentation governance for `.github/**`, Dockerfiles, Compose and delivery tools.

- [ ] **Step 1: Write failing documentation coverage tests**

Append to `tests/test_reference_documentation.py`:

```python
def test_ci_cd_runbook_documents_release_and_rollback_boundaries() -> None:
    runbook = Path("docs/operations/20-ci-cd-and-release.md").read_text(
        encoding="utf-8"
    )

    for term in (
        "GitHub-hosted Runner",
        "PostgreSQL Service Container",
        "IVIDA_TEST_POSTGRES_URL",
        "GHCR",
        "镜像 Digest",
        "Alembic revision",
        "不自动 downgrade",
        "不连接现有服务器",
    ):
        assert term in runbook


def test_delivery_files_are_governed_by_documentation_map() -> None:
    groups = {
        group["name"]: group
        for group in json.loads(
            Path("docs/code-document-map.json").read_text(encoding="utf-8")
        )["groups"]
    }
    delivery = groups["ci-cd-and-delivery"]

    assert ".github/**" in delivery["code_patterns"]
    assert "Dockerfile" in delivery["code_patterns"]
    assert "compose*.yaml" in delivery["code_patterns"]
    assert "docs/operations/20-ci-cd-and-release.md" in delivery["documents"]
```

- [ ] **Step 2: Run RED documentation tests**

```powershell
uv run pytest tests/test_reference_documentation.py -q
```

Expected: missing Runbook and `ci-cd-and-delivery` mapping cause failures.

- [ ] **Step 3: Write the authoritative operations Runbook**

Create `docs/operations/20-ci-cd-and-release.md` with these exact sections and commands:

```markdown
# CI/CD、容器发布与回滚

## 目标和非生产边界
## Pull Request CI
## PostgreSQL Service Container
## 本地 Docker Compose 演示
## Tag、GHCR 与 GitHub Release
## 镜像 Digest 与 Alembic revision
## 应用回滚
## 为什么不自动 downgrade 数据库
## Secret 与 Fork PR
## 失败诊断
## GitHub Branch Protection 设置
## Artifact 与镜像保留策略
```

The Runbook must include:

```powershell
Copy-Item .env.compose.example .env.compose
docker compose --env-file .env.compose up --build -d
uv run python tools/smoke_compose.py
docker compose --env-file .env.compose down
```

It must state that CI uses a GitHub-hosted Runner and PostgreSQL Service Container, sets `IVIDA_TEST_POSTGRES_URL`, publishes to GHCR, records image Digest and Alembic revision, never automatically downgrades production data, and never connects to the inspected server.

- [ ] **Step 4: Update README, local-run guide, and documentation map**

Add a concise “CI/CD 与容器演示” subsection after README's human review/reconciliation section. Start it with these exact badges:

```markdown
[![CI](https://github.com/EdmendZ/IVIDAInvoiceReconciliation/actions/workflows/ci.yml/badge.svg)](https://github.com/EdmendZ/IVIDAInvoiceReconciliation/actions/workflows/ci.yml)
[![CodeQL](https://github.com/EdmendZ/IVIDAInvoiceReconciliation/actions/workflows/codeql.yml/badge.svg)](https://github.com/EdmendZ/IVIDAInvoiceReconciliation/actions/workflows/codeql.yml)
```

Then show the Compose start command, explain Tag release, and link the Runbook without claiming production deployment.

Add one short link from `docs/operations/08-api-ui-and-local-run.md` to the Runbook; do not duplicate release instructions there.

Add this group to `docs/code-document-map.json`:

```json
{
  "name": "ci-cd-and-delivery",
  "code_patterns": [
    ".github/**",
    "Dockerfile",
    "frontend/Dockerfile",
    "frontend/nginx.conf",
    ".dockerignore",
    "frontend/.dockerignore",
    "compose*.yaml",
    ".env.compose.example",
    "tools/smoke_compose.py"
  ],
  "documents": [
    "README.md",
    "docs/operations/20-ci-cd-and-release.md",
    "docs/operations/08-api-ui-and-local-run.md"
  ]
}
```

- [ ] **Step 5: Verify all documentation and delivery contracts**

```powershell
uv run pytest tests/test_reference_documentation.py tests/test_delivery_configuration.py tests/test_documentation_sync.py -q
uv run python tools/check_documentation_sync.py --base-ref origin/main
git diff --check
```

Expected: all checks pass and every delivery change is paired with an operations-document update.

- [ ] **Step 6: Commit Task 7**

```powershell
git add README.md docs/operations/20-ci-cd-and-release.md docs/operations/08-api-ui-and-local-run.md docs/code-document-map.json tests/test_reference_documentation.py tests/test_delivery_configuration.py
git commit -m "docs: explain CI/CD release workflow"
```

---

### Task 8: Run Full Verification and Prove the Public-Repository Flow

**Files:**
- Modify only if verification exposes a defect in a Task 1–7 file.
- Test: all backend, PostgreSQL, frontend, container, Workflow and documentation checks.

**Interfaces:**
- Consumes: the complete delivery system.
- Produces: green PR checks, one verified pre-release, recorded evidence, and a clean worktree.

- [ ] **Step 1: Run fresh local backend and frontend verification**

```powershell
uv run pytest --ignore=tests/test_postgres_reconciliation_case_integration.py
cd frontend
npm test -- --run
npm run typecheck
npm run build
```

Expected: all commands pass with no new warnings.

- [ ] **Step 2: Run a disposable real PostgreSQL acceptance locally**

Start a disposable PostgreSQL 18 container on an unused host port, set both `DATABASE_URL` and `IVIDA_TEST_POSTGRES_URL`, then run:

```powershell
uv run alembic upgrade head
uv run pytest tests/test_postgres_reconciliation_case_integration.py
uv run alembic downgrade -1
uv run alembic upgrade head
uv run alembic current
uv run alembic check
```

Expected: integration tests execute rather than skip; migration downgrade/re-upgrade and autogenerate check pass. Remove only this named disposable container and Volume afterward.

- [ ] **Step 3: Run fresh Compose and image acceptance**

```powershell
Copy-Item .env.compose.example .env.compose
docker compose --env-file .env.compose up --build -d
uv run python tools/smoke_compose.py
docker compose --env-file .env.compose ps
docker compose --env-file .env.compose down -v
```

Expected: PostgreSQL/MinIO/API/Worker/Frontend are healthy or completed as designed, Smoke passes, and owned Volumes are removed.

- [ ] **Step 4: Run governance and whitespace verification**

```powershell
uv run python -m compileall -q app tests tools
uv run python tools/check_documentation_sync.py --base-ref origin/main
uv run pytest tests/test_delivery_configuration.py tests/test_reference_documentation.py tests/test_documentation_sync.py -q
git diff --check
git status --short
```

Expected: all commands pass; status contains only intentional Task changes before the final commit and is clean after it.

- [ ] **Step 5: Open a PR and verify GitHub checks**

Push the feature branch, open a PR, and verify these exact required checks are green:

- `quality`
- `backend`
- `postgres-integration`
- `frontend`
- CodeQL `python`
- CodeQL `javascript-typescript`

Confirm the PostgreSQL Job output shows integration tests executed and Alembic reached the single head.

- [ ] **Step 6: Create one pre-release acceptance Tag**

After merging or from an explicitly approved release candidate Commit, run:

```powershell
git tag v0.0.0-ci.1
git push origin v0.0.0-ci.1
```

Verify that the Release Workflow reuses CI, builds and Smokes all images before registry login, publishes version/SHA tags, records three Digests and the Alembic head, and creates a pre-release. Do not delete remote evidence unless the repository owner explicitly requests cleanup.

- [ ] **Step 7: Commit any verification-only fixes**

If verification required changes, commit only the scoped fixes:

```powershell
git add --update
git commit -m "fix: stabilize CI/CD acceptance"
```

If no files changed, do not create an empty commit.

- [ ] **Step 8: Request final code review**

Use `superpowers:requesting-code-review` over the full implementation range. Fix all Critical and Important findings, run a scoped re-review, then repeat the fresh local test, Compose Smoke and GitHub PR checks before declaring the plan complete.
