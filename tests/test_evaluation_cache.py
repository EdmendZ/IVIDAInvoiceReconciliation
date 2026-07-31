from pathlib import Path

from app.domain.parsing import ParseResult
from app.evaluation.cache import MinerUParseCache


def test_parse_cache_round_trip(tmp_path: Path) -> None:
    cache = MinerUParseCache(tmp_path)
    source = b"%PDF-1.7 fixture"
    result = ParseResult(
        provider="mineru",
        model_name="vlm",
        remote_task_id="remote-1",
        markdown="# Invoice",
        content_blocks=[{"type": "text"}],
        tables=[],
        page_count=1,
        artifact_archive=b"zip-data",
    )

    assert cache.get(source) is None
    key = cache.put(source, result)
    restored = cache.get(source)

    assert key == MinerUParseCache.source_key(source)
    assert restored is not None
    assert restored.markdown == "# Invoice"
    assert restored.artifact_archive == b"zip-data"


def test_pending_job_survives_process_restart(tmp_path: Path) -> None:
    source = b"%PDF pending"
    first = MinerUParseCache(tmp_path)
    first.put_pending(source, "remote-123")

    restarted = MinerUParseCache(tmp_path)

    assert restarted.get_pending(source) == "remote-123"
