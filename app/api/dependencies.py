"""FastAPI 依赖装配：把业务服务需要的具体基础设施集中接线。

路由只依赖服务，不应该知道 PostgreSQL、MinIO 的构造细节。这里相当于一个
轻量级 Composition Root；`lru_cache` 保证无状态客户端和仓储在进程内复用，
但它不承担跨进程缓存或业务数据持久化。
"""

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
from app.infra.postgres_reconciliation_repository import (
    PostgresReconciliationRepository,
)
from app.infra.postgres_admin_repository import PostgresAdminRepository
from app.infra.postgres_reconciliation_case_repository import (
    PostgresReconciliationCaseRepository,
)
from app.services.reconciliation_application_service import (
    ReconciliationApplicationService,
)
from app.infra.postgres_worker_runtime_repository import (
    PostgresWorkerRuntimeRepository,
)
from app.services.runtime_status_service import RuntimeStatusService
from app.services.reconciliation_case_service import ReconciliationCaseService


@lru_cache
def get_object_storage() -> MinioObjectStorage:
    """按环境配置创建 MinIO 适配器，并在当前 API 进程内复用。"""
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
    """返回抽取任务仓储；任务描述一份上传文件当前所处的生命周期。"""
    return PostgresExtractionTaskRepository(get_session_factory())


@lru_cache
def get_parse_repository() -> PostgresParseResultRepository:
    """返回解析结果仓储；保存 MinerU 产出的原始文本与版面信息。"""
    return PostgresParseResultRepository(get_session_factory())


@lru_cache
def get_draft_repository() -> PostgresDocumentDraftRepository:
    """返回结构化草稿仓储；草稿仍可被人工修订，不能直接参与对账。"""
    return PostgresDocumentDraftRepository(get_session_factory())


@lru_cache
def get_review_repository() -> PostgresReviewRepository:
    """返回审核仓储；它负责不可变版本和审核动作的事务写入。"""
    return PostgresReviewRepository(get_session_factory())


@lru_cache
def get_run_repository() -> PostgresExtractionRunRepository:
    """返回模型运行仓储；同一任务重试时可以产生多个 Run。"""
    return PostgresExtractionRunRepository(get_session_factory())


@lru_cache
def get_review_service() -> ReviewService:
    """装配人工审核用例及其校验、草稿、版本依赖。"""
    return ReviewService(
        review_repository=get_review_repository(),
        draft_repository=get_draft_repository(),
        run_repository=get_run_repository(),
        validation_service=ValidationService(),
    )


@lru_cache
def get_reconciliation_application_service() -> ReconciliationApplicationService:
    """装配对账入口；只读取已批准版本并写入可审计的对账记录。"""
    return ReconciliationApplicationService(
        review_repository=get_review_repository(),
        reconciliation_repository=PostgresReconciliationRepository(
            get_session_factory()
        ),
    )


@lru_cache
def get_reconciliation_case_repository() -> PostgresReconciliationCaseRepository:
    """返回差异 Case 仓储，统一承载读模型和乐观锁写入。"""

    return PostgresReconciliationCaseRepository(get_session_factory())


@lru_cache
def get_admin_repository() -> PostgresAdminRepository:
    """返回后台用户仓储，供认证和 Case 分派读取同一账号事实。"""

    return PostgresAdminRepository(get_session_factory())


@lru_cache
def get_reconciliation_case_service() -> ReconciliationCaseService:
    """装配差异处理工作流及有效 Reviewer 查询。"""

    return ReconciliationCaseService(
        get_reconciliation_case_repository(),
        active_reviewer_reader=get_admin_repository(),
    )


@lru_cache
def get_document_upload_service() -> DocumentUploadService:
    """装配上传用例，并把最大文件大小这一基础设施策略注入服务。"""
    settings = get_settings()
    return DocumentUploadService(
        storage=get_object_storage(),
        repository=get_task_repository(),
        max_bytes=settings.upload_max_bytes,
    )


@lru_cache
def get_extraction_service() -> ExtractionService:
    """装配 API 侧抽取控制服务。

    真正的模型调用在 Worker 进程中完成，所以 API 使用禁用 Provider，避免
    请求线程误触发昂贵且耗时的外部调用。
    """
    return ExtractionService(
        storage=get_object_storage(),
        task_repository=get_task_repository(),
        run_repository=get_run_repository(),
        provider=DisabledExtractionProvider(),
    )


@lru_cache
def get_worker_runtime_repository() -> PostgresWorkerRuntimeRepository:
    """返回 Worker 心跳仓储，供 UI 判断队列是否有消费者。"""
    return PostgresWorkerRuntimeRepository(get_session_factory())


@lru_cache
def get_runtime_status_service() -> RuntimeStatusService:
    """装配运行状态查询，并注入 Worker 失联判定阈值。"""
    settings = get_settings()
    return RuntimeStatusService(
        get_worker_runtime_repository(),
        offline_after_seconds=settings.worker_offline_after_seconds,
    )
