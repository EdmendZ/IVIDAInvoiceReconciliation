from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

from app.domain.parsing import ParseResult


class MinerUParseCache:
    def __init__(self, root: Path) -> None:
        self._root = root

    @staticmethod
    def source_key(content: bytes) -> str:
        return sha256(content).hexdigest()

    def get(self, content: bytes) -> ParseResult | None:
        key = self.source_key(content)
        metadata_path = self._root / f"{key}.json"
        archive_path = self._root / f"{key}.zip"
        if not metadata_path.exists() or not archive_path.exists():
            return None
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        return ParseResult(
            **payload,
            artifact_archive=archive_path.read_bytes(),
        )

    def put(self, content: bytes, result: ParseResult) -> str:
        key = self.source_key(content)
        self._root.mkdir(parents=True, exist_ok=True)
        metadata_path = self._root / f"{key}.json"
        archive_path = self._root / f"{key}.zip"
        payload = result.model_dump(
            mode="json",
            exclude={"artifact_archive"},
        )
        metadata_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        archive_path.write_bytes(result.artifact_archive)
        pending_path = self._root / f"{key}.pending.json"
        pending_path.unlink(missing_ok=True)
        return key

    def get_pending(self, content: bytes) -> str | None:
        key = self.source_key(content)
        path = self._root / f"{key}.pending.json"
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        return str(payload["remote_job_id"])

    def put_pending(self, content: bytes, remote_job_id: str) -> None:
        key = self.source_key(content)
        self._root.mkdir(parents=True, exist_ok=True)
        path = self._root / f"{key}.pending.json"
        path.write_text(
            json.dumps(
                {
                    "source_sha256": key,
                    "remote_job_id": remote_job_id,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
