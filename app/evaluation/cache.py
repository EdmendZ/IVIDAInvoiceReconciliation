"""MinerU 评测缓存。

解析 PDF/图片通常比结构化归一化更慢、成本也更高。缓存以原件 SHA-256 为键，
让不同 Prompt/模型方案共享同一解析结果，保证对照实验只改变归一化变量。
"""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

from app.domain.parsing import ParseResult


class MinerUParseCache:
    """在本地目录缓存已完成结果，并记录尚未结束的远端任务 ID。"""

    def __init__(self, root: Path) -> None:
        """保存缓存根目录；目录在首次写入时惰性创建。"""
        self._root = root

    @staticmethod
    def source_key(content: bytes) -> str:
        """由文件内容生成稳定键，避免文件改名导致重复调用。"""
        return sha256(content).hexdigest()

    def get(self, content: bytes) -> ParseResult | None:
        """读取完整解析结果；元数据或附件缺一时都视为缓存未命中。"""
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
        """原子语义地完成缓存：写结果后清除对应的 pending 标记。"""
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
        """取得未完成的 MinerU 任务 ID，支持评测进程中断后继续轮询。"""
        key = self.source_key(content)
        path = self._root / f"{key}.pending.json"
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        return str(payload["remote_job_id"])

    def put_pending(self, content: bytes, remote_job_id: str) -> None:
        """在提交远端任务后立即落盘任务 ID，防止重启造成重复提交。"""
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
