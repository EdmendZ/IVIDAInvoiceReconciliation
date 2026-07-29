from __future__ import annotations

import io
import json
import os
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from app.domain.parsing import (
    ParserPollResult,
    ParserSubmission,
    ParseResult,
    ParseState,
)
from app.infra.external_errors import ExternalServiceError


class MinerUPrecisionParser:
    provider_name = "mineru"

    def __init__(
        self,
        *,
        client: Any,
        model_name: str = "vlm",
        language: str = "en",
        timeout_seconds: int = 600,
    ) -> None:
        self._client = client
        self.model_name = model_name
        self._language = language
        self._timeout_seconds = timeout_seconds

    @classmethod
    def create(
        cls,
        *,
        token: str,
        base_url: str,
        model_name: str = "vlm",
        language: str = "en",
        timeout_seconds: int = 600,
    ) -> "MinerUPrecisionParser":
        if not token:
            raise ValueError("MinerU API token is required")
        from mineru import MinerU

        return cls(
            client=MinerU(token, base_url=base_url),
            model_name=model_name,
            language=language,
            timeout_seconds=timeout_seconds,
        )

    def submit(
        self,
        *,
        filename: str,
        content_type: str,
        content: bytes,
    ) -> ParserSubmission:
        del content_type
        suffix = Path(filename).suffix.lower() or ".bin"
        temporary_path = ""
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
                handle.write(content)
                temporary_path = handle.name
            batch_id = self._client.submit(
                temporary_path,
                model=self.model_name,
                ocr=True,
                table=True,
                formula=False,
                language=self._language,
            )
            return ParserSubmission(remote_job_id=str(batch_id))
        except Exception as exc:
            raise self._safe_error(exc, operation="submit") from exc
        finally:
            if temporary_path:
                try:
                    os.unlink(temporary_path)
                except FileNotFoundError:
                    pass

    def poll(self, remote_job_id: str) -> ParserPollResult:
        try:
            results = self._client.get_batch(remote_job_id)
            if not results:
                return ParserPollResult(
                    state=ParseState.RUNNING,
                    progress=0,
                )
            sdk_result = results[0]
            state = str(getattr(sdk_result, "state", "")).lower()
            progress = self._progress(getattr(sdk_result, "progress", 0))
            if state == "done":
                return ParserPollResult(
                    state=ParseState.SUCCEEDED,
                    progress=100,
                    result=self._build_result(sdk_result),
                )
            if state == "failed":
                return ParserPollResult(
                    state=ParseState.FAILED,
                    progress=progress,
                    error_code="MINERU_PARSE_FAILED",
                    error_message="MinerU could not parse the document",
                )
            return ParserPollResult(
                state=ParseState.RUNNING,
                progress=progress,
            )
        except Exception as exc:
            raise self._safe_error(exc, operation="poll") from exc

    def _build_result(self, sdk_result: Any) -> ParseResult:
        markdown = str(getattr(sdk_result, "markdown", "") or "")
        content_blocks = self._json_list(
            getattr(sdk_result, "content_list", None)
        )
        tables = [
            block
            for block in content_blocks
            if str(block.get("type", "")).lower() in {"table", "table_body"}
        ]
        page_count = self._page_count(content_blocks)
        task_id = getattr(sdk_result, "task_id", None)
        archive = self._package_artifacts(
            markdown=markdown,
            content_blocks=content_blocks,
            images=getattr(sdk_result, "images", None),
            remote_task_id=str(task_id) if task_id else None,
        )
        return ParseResult(
            provider=self.provider_name,
            model_name=self.model_name,
            remote_task_id=str(task_id) if task_id else None,
            markdown=markdown,
            content_blocks=content_blocks,
            tables=tables,
            page_count=page_count,
            artifact_archive=archive,
        )

    @staticmethod
    def _json_list(value: Any) -> list[dict]:
        if value is None:
            return []
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                return []
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, dict)]

    @staticmethod
    def _page_count(content_blocks: list[dict]) -> int:
        page_indexes: list[int] = []
        for block in content_blocks:
            page = block.get("page_idx", block.get("page"))
            if isinstance(page, int):
                page_indexes.append(page)
        if not page_indexes:
            return 0
        return max(page_indexes) + (1 if min(page_indexes) == 0 else 0)

    @staticmethod
    def _progress(value: Any) -> int:
        try:
            return max(0, min(100, int(value or 0)))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _package_artifacts(
        *,
        markdown: str,
        content_blocks: list[dict],
        images: Any,
        remote_task_id: str | None,
    ) -> bytes:
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("document.md", markdown)
            archive.writestr(
                "content_list.json",
                json.dumps(content_blocks, ensure_ascii=False, indent=2),
            )
            archive.writestr(
                "manifest.json",
                json.dumps(
                    {
                        "provider": "mineru",
                        "remote_task_id": remote_task_id,
                        "image_count": len(images) if isinstance(images, list) else 0,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            )
            if isinstance(images, list):
                for index, image in enumerate(images):
                    content = getattr(image, "content", None)
                    if isinstance(content, bytes):
                        filename = Path(
                            str(getattr(image, "filename", f"image-{index}.bin"))
                        ).name
                        archive.writestr(f"images/{filename}", content)
        return output.getvalue()

    @staticmethod
    def _safe_error(exc: Exception, *, operation: str) -> ExternalServiceError:
        name = exc.__class__.__name__.lower()
        status_code = getattr(exc, "status_code", None)
        if "timeout" in name:
            return ExternalServiceError(
                "MINERU_TIMEOUT",
                f"MinerU {operation} timed out",
                retryable=True,
            )
        if status_code == 429:
            return ExternalServiceError(
                "MINERU_RATE_LIMITED",
                "MinerU rate limit reached",
                retryable=True,
            )
        if isinstance(status_code, int) and status_code >= 500:
            return ExternalServiceError(
                "MINERU_UNAVAILABLE",
                "MinerU is temporarily unavailable",
                retryable=True,
            )
        if status_code in {401, 403} or "auth" in name:
            return ExternalServiceError(
                "MINERU_AUTH_FAILED",
                "MinerU authentication failed",
                retryable=False,
            )
        return ExternalServiceError(
            "MINERU_REQUEST_FAILED",
            f"MinerU {operation} failed",
            retryable=False,
        )
