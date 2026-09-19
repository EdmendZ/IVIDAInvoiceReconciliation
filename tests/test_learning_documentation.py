from pathlib import Path


def test_architecture_explains_core_runtime_boundaries() -> None:
    architecture = Path("docs/architecture.md").read_text(encoding="utf-8")
    terms = [
        "PostgreSQL",
        "MinIO",
        "MinerU",
        "HttpOnly Session",
        "tenant/store",
        "fencing",
        "幂等键",
        "ws_confirmations",
    ]

    for term in terms:
        assert term in architecture, term


def test_worked_example_links_each_core_business_stage_to_source() -> None:
    example = Path("docs/demo.md").read_text(encoding="utf-8")
    source_files = [
        "document_upload_service.py",
        "extraction_worker.py",
        "validation_service.py",
        "review_service.py",
        "candidate_matching_service.py",
        "reconciliation_service.py",
        "postgres_reconciliation_repository.py",
    ]

    for filename in source_files:
        assert filename in example, filename
