import json
from pathlib import Path

from tools.check_documentation_sync import missing_document_updates


def _groups() -> list[dict]:
    mapping = Path("docs/code-document-map.json")
    return json.loads(mapping.read_text(encoding="utf-8"))["groups"]


def test_documentation_map_references_existing_files() -> None:
    for group in _groups():
        assert group["code_patterns"]
        for document in group["documents"]:
            assert Path(document).is_file(), document


def test_worker_change_requires_extraction_document_update() -> None:
    missing = missing_document_updates(
        {"app/workers/extraction_worker.py"},
        _groups(),
    )
    assert missing[0][0] == "document-lifecycle-and-worker"

    covered = missing_document_updates(
        {
            "app/workers/extraction_worker.py",
            "docs/ai/04-extraction-pipeline.md",
        },
        _groups(),
    )
    assert not covered
