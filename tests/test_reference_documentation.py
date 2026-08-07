import json
import re
from pathlib import Path


def test_database_dictionary_lists_every_orm_table() -> None:
    source = Path("app/infra/database_models.py").read_text(encoding="utf-8")
    dictionary = Path("docs/reference/12-database-dictionary.md").read_text(
        encoding="utf-8"
    )
    table_names = re.findall(r'__tablename__ = "([^"]+)"', source)

    assert table_names
    for table_name in table_names:
        assert f"`{table_name}`" in dictionary, table_name


def test_api_reference_lists_business_endpoint_templates() -> None:
    reference = Path("docs/reference/11-api-contracts.md").read_text(
        encoding="utf-8"
    )
    endpoint_templates = [
        "/api/documents/upload",
        "/api/extraction-tasks/{task_id}/extract",
        "/api/extraction-runs/{run_id}/result",
        "/api/extraction-runs/{run_id}/cancel",
        "/api/review/tasks/{task_id}/start",
        "/api/review/versions/{version_id}/validate",
        "/api/review/versions/{version_id}/approve",
        "/api/reconciliations/candidates",
        "/api/reconciliations",
        "/api/runtime/status",
    ]

    for endpoint in endpoint_templates:
        assert endpoint in reference, endpoint


def test_case_api_is_documented() -> None:
    contracts = Path("docs/reference/11-api-contracts.md").read_text(
        encoding="utf-8"
    )

    assert "/api/reconciliation-cases/{case_id}/claim" in contracts
    assert "/api/reconciliation-cases/{case_id}/approve" in contracts
    assert "CASE_REVISION_CONFLICT" in contracts


def test_case_error_and_database_ownership_guards_are_documented() -> None:
    troubleshooting = Path(
        "docs/operations/13-error-codes-and-troubleshooting.md"
    ).read_text(encoding="utf-8")
    dictionary = Path("docs/reference/12-database-dictionary.md").read_text(
        encoding="utf-8"
    )

    assert "| CASE_REVIEWER_REQUIRED | 403 |" in troubleshooting
    assert "(case_id, reconciliation_id)" in dictionary
    assert "(line_result_id, reconciliation_id)" in dictionary
    assert "(item_id, case_id)" in dictionary
    assert "INSERT、UPDATE 和 DELETE" in dictionary


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
    assert "app/services/reconciliation_case_*.py" in reconciliation_patterns
    assert (
        "app/infra/postgres_reconciliation_case_repository.py"
        in reconciliation_patterns
    )
    assert "frontend/src/cases/**" in reconciliation_patterns
    assert "frontend/src/cases/**" in api_ui_patterns


def test_troubleshooting_guide_lists_validation_rule_codes() -> None:
    source = Path("app/services/validation_service.py").read_text(
        encoding="utf-8"
    )
    guide = Path(
        "docs/operations/13-error-codes-and-troubleshooting.md"
    ).read_text(encoding="utf-8")
    rule_codes = re.findall(r'rule_code="([A-Z0-9_]+)"', source)

    assert rule_codes
    for rule_code in rule_codes:
        assert rule_code in guide, rule_code


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
