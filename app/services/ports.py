"""应用服务依赖的基础设施端口。

Service 只依赖这些 Protocol，不依赖 SQLAlchemy、MinIO 或第三方 SDK，因此
测试可使用 Fake，生产可使用 PostgreSQL/MinIO 实现。
"""

from typing import Protocol

from datetime import datetime

from app.domain.extraction_runs import ExtractionRun, ExtractionRunStatus
from app.domain.extraction_tasks import ExtractionStatus
from app.domain.extraction_tasks import ExtractionTask
from app.domain.parse_results import ParseResultRecord
from app.domain.document_drafts import DocumentDraft, DraftBundle
from app.domain.normalization import FieldEvidence
from app.domain.validation import ValidationIssue
from app.domain.worker_runtime import WorkerHeartbeat


class ObjectStorage(Protocol):
    """保存和读取不可结构化二进制对象。"""

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
    """上传文件级 Task 的持久化端口。"""

    def create(self, task: ExtractionTask) -> None: ...

    def get(self, task_id: str) -> ExtractionTask | None: ...

    def list_recent(self, limit: int = 100) -> list[ExtractionTask]: ...

    def update_status(
        self,
        task_id: str,
        status: ExtractionStatus,
        error_message: str | None = None,
    ) -> None: ...


class ExtractionRunRepository(Protocol):
    """异步 Run 状态机、调度、租约、取消和溯源端口。"""

    def create(self, run: ExtractionRun) -> None: ...

    def get(self, run_id: str) -> ExtractionRun | None: ...

    def get_latest_for_task(self, task_id: str) -> ExtractionRun | None: ...

    def claim_next(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
        now: datetime,
    ) -> ExtractionRun | None:
        """原子领取一条可执行 Run，并设置短租约。"""
        ...

    def set_remote_job(
        self,
        run_id: str,
        *,
        remote_job_id: str,
        next_attempt_at: datetime,
    ) -> None:
        """保存远端 Job 并将 Run 调度到 parsing。"""
        ...

    def schedule_poll(
        self,
        run_id: str,
        *,
        next_attempt_at: datetime,
        increment_attempt: bool = False,
    ) -> None:
        """释放租约，把下一次执行安排到指定时间。"""
        ...

    def set_status(
        self,
        run_id: str,
        status: ExtractionRunStatus,
        *,
        release_lease: bool = True,
    ) -> None: ...

    def mark_ready_for_review(
        self,
        run_id: str,
        *,
        normalized_output: dict,
        input_tokens: int | None,
        output_tokens: int | None,
        estimated_cost_aud: str | None,
        normalization_latency_ms: int,
    ) -> None:
        """以原子状态更新结束机器抽取并保存计量信息。"""
        ...

    def set_model_provenance(
        self,
        run_id: str,
        *,
        parser_provider: str,
        parser_model: str,
        normalizer_provider: str,
        normalizer_model: str,
        prompt_version: str,
    ) -> None:
        """记录产生本次结果的 Parser、Normalizer 和 Prompt。"""
        ...

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

    def fail(
        self,
        run_id: str,
        error_message: str,
        *,
        error_code: str | None = None,
    ) -> None:
        """将 Run 置为失败并保存稳定错误码和安全消息。"""
        ...

    def request_cancel(
        self,
        run_id: str,
        *,
        requested_by: str,
        requested_at: datetime,
    ) -> ExtractionRun | None:
        """幂等记录取消请求；queued Run 可以立即取消。"""
        ...

    def is_cancel_requested(self, run_id: str) -> bool: ...

    def mark_cancelled(
        self,
        run_id: str,
        *,
        stage: str,
        remote_may_continue: bool,
    ) -> ExtractionRun | None: ...


class ParseResultRepository(Protocol):
    """按 Run 保存和读取可复用 Parser 输出。"""

    def create(self, result: ParseResultRecord) -> None: ...

    def get_for_run(self, run_id: str) -> ParseResultRecord | None: ...


class DocumentDraftRepository(Protocol):
    """原子保存 Draft、Evidence 和 Validation Issues。"""

    def create_with_evidence_and_issues(
        self,
        draft: DocumentDraft,
        evidence: list[FieldEvidence],
        issues: list[ValidationIssue],
    ) -> DocumentDraft: ...

    def get_for_run(self, run_id: str) -> DraftBundle | None: ...

    def get_for_task(self, task_id: str) -> DraftBundle | None: ...

    def list_latest(self) -> list[DraftBundle]: ...


class WorkerRuntimeRepository(Protocol):
    """写入和读取 Worker 心跳，不承担任务队列功能。"""

    def heartbeat(
        self,
        *,
        worker_id: str,
        version: str,
        now: datetime,
    ) -> None: ...

    def latest(self) -> WorkerHeartbeat | None: ...
