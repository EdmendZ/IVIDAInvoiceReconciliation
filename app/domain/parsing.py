from __future__ import annotations

from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field


class ParseState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ParserSubmission(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    remote_job_id: str = Field(min_length=1)


class ParseResult(BaseModel):
    provider: str
    model_name: str
    remote_task_id: str | None = None
    markdown: str
    content_blocks: list[dict] = Field(default_factory=list)
    tables: list[dict] = Field(default_factory=list)
    page_count: int = Field(default=0, ge=0)
    artifact_archive: bytes = Field(default=b"", exclude=True, repr=False)


class ParserPollResult(BaseModel):
    state: ParseState
    progress: int = Field(default=0, ge=0, le=100)
    result: ParseResult | None = None
    error_code: str | None = None
    error_message: str | None = None


class AsyncDocumentParser(Protocol):
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
    ) -> ParserSubmission: ...

    def poll(self, remote_job_id: str) -> ParserPollResult: ...
