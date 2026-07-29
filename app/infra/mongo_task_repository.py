from pymongo import ASCENDING, MongoClient
from pymongo.collection import Collection

from app.domain.extraction_tasks import ExtractionTask


class MongoExtractionTaskRepository:
    def __init__(self, mongo_url: str, database_name: str) -> None:
        client: MongoClient = MongoClient(
            mongo_url,
            serverSelectionTimeoutMS=3000,
            tz_aware=True,
        )
        self._collection: Collection = client[database_name]["extraction_tasks"]
        self._indexes_ready = False

    def _ensure_indexes(self) -> None:
        if self._indexes_ready:
            return
        self._collection.create_index(
            [("task_id", ASCENDING)],
            unique=True,
            name="task_id_unique",
        )
        self._collection.create_index(
            [("created_at", ASCENDING)],
            name="created_at",
        )
        self._indexes_ready = True

    def create(self, task: ExtractionTask) -> None:
        self._ensure_indexes()
        document = task.model_dump(mode="json")
        document["_id"] = task.task_id
        self._collection.insert_one(document)

    def get(self, task_id: str) -> ExtractionTask | None:
        document = self._collection.find_one({"_id": task_id})
        if document is None:
            return None
        document.pop("_id", None)
        return ExtractionTask.model_validate(document)

