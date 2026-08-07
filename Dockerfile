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
