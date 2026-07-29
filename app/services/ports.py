from typing import Protocol

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


class ExtractionTaskRepository(Protocol):
    def create(self, task: ExtractionTask) -> None: ...

    def get(self, task_id: str) -> ExtractionTask | None: ...

