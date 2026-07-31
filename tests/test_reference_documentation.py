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
