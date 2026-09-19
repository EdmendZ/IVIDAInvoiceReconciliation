import json
from pathlib import Path


def test_architecture_points_to_runtime_api_and_database_sources() -> None:
    architecture = Path("docs/architecture.md").read_text(encoding="utf-8")

    for term in (
        "database_models.py",
        "Alembic migration",
        "`/docs`",
        "ws_documents",
        "ws_previews",
        "ws_confirmations",
        "事务锁",
        "CSRF/Origin",
    ):
        assert term in architecture, term


def test_case_sources_are_mapped_to_reconciliation_and_ui_documents() -> None:
    groups = {
        group["name"]: group
        for group in json.loads(
            Path("docs/code-document-map.json").read_text(encoding="utf-8")
        )["groups"]
    }
    reconciliation_patterns = groups["reconciliation"]["code_patterns"]
    api_ui_patterns = groups["api-ui-and-operations"]["code_patterns"]

    assert "app/domain/reconciliation_cases.py" in reconciliation_patterns
    assert "app/services/reconciliation*.py" in reconciliation_patterns
    assert (
        "app/infra/postgres_reconciliation_case_repository.py"
        in reconciliation_patterns
    )
    assert "frontend/src/cases/**" in reconciliation_patterns
    assert "frontend/src/**" in api_ui_patterns


def test_ci_cd_runbook_documents_release_and_rollback_boundaries() -> None:
    runbook = Path("docs/development.md").read_text(encoding="utf-8")

    for term in (
        "GitHub-hosted Runner",
        "PostgreSQL Service Container",
        "IVIDA_TEST_POSTGRES_URL",
        "GHCR",
        "downgrade",
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
    assert "docs/development.md" in delivery["documents"]
