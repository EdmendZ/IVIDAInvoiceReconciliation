from typing import Protocol

from app.domain.extraction_runs import ExtractionRun, ExtractionRunStatus
from app.domain.extraction_tasks import ExtractionStatus
from app.domain.extraction_tasks import ExtractionTask


class ObjectStorage(Protocol):
    @property
    def bucket_name(self) -> str: ...

    def put(
        self,
        object_key: str,
        data: bytes,
        content_type: str,
    ) -> None: ...

    def delete(self, object_key: str) -> None: ...

    def get(self, object_key: str) -> bytes: ...


class ExtractionTaskRepository(Protocol):
    def create(self, task: ExtractionTask) -> None: ...

    def get(self, task_id: str) -> ExtractionTask | None: ...

    def update_status(
        self,
        task_id: str,
        status: ExtractionStatus,
        error_message: str | None = None,
    ) -> None: ...


class ExtractionRunRepository(Protocol):
    def create(self, run: ExtractionRun) -> None: ...

    def get(self, run_id: str) -> ExtractionRun | None: ...

    def complete(
        self,
        run_id: str,
        *,
        raw_output: dict,
        normalized_output: dict,
        latency_ms: int,
        input_tokens: int | None,
        output_tokens: int | None,
        estimated_cost_aud: str | None,
    ) -> None: ...

    def fail(self, run_id: str, error_message: str) -> None: ...
