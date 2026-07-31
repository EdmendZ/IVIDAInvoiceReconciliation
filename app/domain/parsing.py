from __future__ import annotations

"""异步文档 Parser 的供应商无关领域契约。"""

from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field


class ParseState(StrEnum):
    """远端解析 Job 被归一化后的通用状态。"""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ParserSubmission(BaseModel):
    """提交成功后用于后续轮询的远端 Job 标识。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    remote_job_id: str = Field(min_length=1)


class ParseResult(BaseModel):
    """Parser 产生的文本、版面块、表格和可审计产物。"""

    provider: str
    model_name: str
    remote_task_id: str | None = None
    markdown: str
    content_blocks: list[dict] = Field(default_factory=list)
    tables: list[dict] = Field(default_factory=list)
    page_count: int = Field(default=0, ge=0)
    artifact_archive: bytes = Field(default=b"", exclude=True, repr=False)


class ParserPollResult(BaseModel):
    """一次轮询结果；仅 succeeded 时 result 应存在。"""

    state: ParseState
    progress: int = Field(default=0, ge=0, le=100)
    result: ParseResult | None = None
    error_code: str | None = None
    error_message: str | None = None


class AsyncDocumentParser(Protocol):
    """提交/轮询式 Parser Protocol，隔离 MinerU 等具体 SDK。"""

    @property
    def provider_name(self) -> str: ...

    @property
    def model_name(self) -> str: ...

    def submit(
        self,
        *,
        filename: str,
        content_type: str,
        content: bytes,
    ) -> ParserSubmission:
        """提交原件并快速返回远端 Job ID。"""
        ...

    def poll(self, remote_job_id: str) -> ParserPollResult:
        """查询远端 Job，不在 Protocol 内执行阻塞等待。"""
        ...
