from app.domain.extraction_tasks import ExtractionTask


class InMemoryObjectStorage:
    def __init__(self) -> None:
        self._bucket_name = "test-invoice-documents"
        self.objects: dict[str, tuple[bytes, str]] = {}

    @property
    def bucket_name(self) -> str:
        return self._bucket_name

    def put(self, object_key: str, data: bytes, content_type: str) -> None:
        self.objects[object_key] = (data, content_type)

    def delete(self, object_key: str) -> None:
        self.objects.pop(object_key, None)


class InMemoryExtractionTaskRepository:
    def __init__(self) -> None:
        self.tasks: dict[str, ExtractionTask] = {}

    def create(self, task: ExtractionTask) -> None:
        self.tasks[task.task_id] = task

    def get(self, task_id: str) -> ExtractionTask | None:
        return self.tasks.get(task_id)

