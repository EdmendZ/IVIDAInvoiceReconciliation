from functools import lru_cache

from app.core.config import get_settings
from app.infra.database import get_session_factory
from app.infra.minio_storage import MinioObjectStorage
from app.infra.postgres_extraction_run_repository import (
    PostgresExtractionRunRepository,
)
from app.infra.postgres_task_repository import PostgresExtractionTaskRepository
from app.infra.postgres_draft_repository import PostgresDocumentDraftRepository
from app.infra.postgres_parse_repository import PostgresParseResultRepository
from app.services.document_upload_service import DocumentUploadService
from app.services.extraction_provider import DisabledExtractionProvider
from app.services.extraction_service import ExtractionService
from app.infra.postgres_review_repository import PostgresReviewRepository
from app.services.review_service import ReviewService
from app.services.validation_service import ValidationService


@lru_cache
def get_object_storage() -> MinioObjectStorage:
    settings = get_settings()
    return MinioObjectStorage(
        endpoint=settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        bucket_name=settings.minio_bucket_name,
        secure=settings.minio_secure,
    )


@lru_cache
def get_task_repository() -> PostgresExtractionTaskRepository:
    return PostgresExtractionTaskRepository(get_session_factory())


@lru_cache
def get_parse_repository() -> PostgresParseResultRepository:
    return PostgresParseResultRepository(get_session_factory())


@lru_cache
def get_draft_repository() -> PostgresDocumentDraftRepository:
    return PostgresDocumentDraftRepository(get_session_factory())


@lru_cache
def get_review_repository() -> PostgresReviewRepository:
    return PostgresReviewRepository(get_session_factory())


@lru_cache
def get_review_service() -> ReviewService:
    return ReviewService(
        review_repository=get_review_repository(),
        draft_repository=get_draft_repository(),
        validation_service=ValidationService(),
    )


@lru_cache
def get_document_upload_service() -> DocumentUploadService:
    settings = get_settings()
    return DocumentUploadService(
        storage=get_object_storage(),
        repository=get_task_repository(),
        max_bytes=settings.upload_max_bytes,
    )


@lru_cache
def get_extraction_service() -> ExtractionService:
    return ExtractionService(
        storage=get_object_storage(),
        task_repository=get_task_repository(),
        run_repository=PostgresExtractionRunRepository(get_session_factory()),
        provider=DisabledExtractionProvider(),
    )
