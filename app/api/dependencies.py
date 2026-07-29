from functools import lru_cache

from app.core.config import get_settings
from app.infra.minio_storage import MinioObjectStorage
from app.infra.mongo_task_repository import MongoExtractionTaskRepository
from app.services.document_upload_service import DocumentUploadService


@lru_cache
def get_document_upload_service() -> DocumentUploadService:
    settings = get_settings()
    storage = MinioObjectStorage(
        endpoint=settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        bucket_name=settings.minio_bucket_name,
        secure=settings.minio_secure,
    )
    repository = MongoExtractionTaskRepository(
        mongo_url=settings.mongo_url,
        database_name=settings.mongo_db_name,
    )
    return DocumentUploadService(
        storage=storage,
        repository=repository,
        max_bytes=settings.upload_max_bytes,
    )

