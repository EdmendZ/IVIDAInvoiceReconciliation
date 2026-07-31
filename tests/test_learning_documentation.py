from pathlib import Path


def test_every_architecture_decision_is_listed_in_adr_index() -> None:
    directory = Path("docs/architecture/decisions")
    index = (directory / "README.md").read_text(encoding="utf-8")
    decisions = sorted(directory.glob("[0-9][0-9][0-9][0-9]-*.md"))

    assert decisions
    for decision in decisions:
        text = decision.read_text(encoding="utf-8")
        assert decision.name in index, decision.name
        assert "- 状态：" in text, decision.name
        assert "## 背景" in text, decision.name
        assert "## 决策" in text, decision.name
        assert "## 结果" in text, decision.name


def test_glossary_defines_terms_used_in_interview_story() -> None:
    glossary = Path("docs/reference/15-glossary.md").read_text(
        encoding="utf-8"
    )
    terms = [
        "ExtractionTask",
        "ExtractionRun",
        "DocumentDraft",
        "DocumentVersion",
        "Evidence",
        "Candidate",
        "SKIP LOCKED",
        "Prompt Version",
        "Gold",
    ]

    for term in terms:
        assert term in glossary, term


def test_worked_example_links_each_core_business_stage_to_source() -> None:
    example = Path(
        "docs/tutorial/16-end-to-end-worked-example.md"
    ).read_text(encoding="utf-8")
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
