"""HTTP 用例层的 Run 排队、查询和取消服务。

真实长任务由 ExtractionWorker 推进；这里不在请求线程内等待 MinerU/LLM。
保留的 execute 方法是同步 Provider Contract 的兼容路径，不是当前 UI 主链路。
"""

from __future__ import annotations

from datetime import UTC, datetime
from time import perf_counter
from uuid import uuid4

from app.domain.documents import Invoice, ReceiveNote
from app.domain.extraction_runs import ExtractionRun, ExtractionRunStatus
from app.domain.extraction_tasks import ExtractionStatus
from app.services.document_upload_service import ExtractionTaskNotFound
from app.services.extraction_provider import ExtractionProvider
from app.services.ports import (
    ExtractionRunRepository,
    ExtractionTaskRepository,
    ObjectStorage,
)


class ExtractionRunNotFound(LookupError):
    """请求的处理尝试不存在。"""

    pass


class ExtractionStateConflict(RuntimeError):
    """当前 Task/Run 状态不允许请求的转换。"""

    pass


class ExtractionService:
    """管理 Run 的生命周期入口，但不承担异步阶段编排。"""

    def __init__(
        self,
        *,
        storage: ObjectStorage,
        task_repository: ExtractionTaskRepository,
        run_repository: ExtractionRunRepository,
        provider: ExtractionProvider,
    ) -> None:
        self._storage = storage
        self._task_repository = task_repository
        self._run_repository = run_repository
        self._provider = provider

    def queue(self, task_id: str) -> ExtractionRun:
        """为可处理 Task 创建一次新的、可审计的 Run。"""

        task = self._task_repository.get(task_id)
        if task is None:
            raise ExtractionTaskNotFound(task_id)
        if task.status not in {ExtractionStatus.UPLOADED, ExtractionStatus.FAILED}:
            raise ExtractionStateConflict(
                f"Task in status '{task.status}' cannot start extraction"
            )

        now = datetime.now(UTC)
        run = ExtractionRun(
            run_id=str(uuid4()),
            task_id=task.task_id,
            provider=self._provider.provider_name,
            model_name=self._provider.model_name,
            status=ExtractionRunStatus.QUEUED,
            next_attempt_at=now,
            started_at=now,
            created_at=now,
        )
        # 先创建 Run 再标记 Task extracting，确保状态指向一个真实处理尝试。
        self._run_repository.create(run)
        self._task_repository.update_status(
            task.task_id,
            ExtractionStatus.EXTRACTING,
        )
        return run

    def execute(self, task_id: str, run_id: str) -> None:
        """执行旧的同步 Provider Contract；当前生产路径使用独立 Worker。"""

        task = self._task_repository.get(task_id)
        if task is None:
            self._run_repository.fail(run_id, "Extraction task no longer exists")
            return

        started = perf_counter()
        try:
            content = self._storage.get(task.storage_object_key)
            result = self._provider.extract(
                document_type=task.document_type,
                filename=task.original_filename,
                content_type=task.content_type,
                content=content,
            )
            normalized = result.normalized_document
            if task.document_type.value == "invoice":
                normalized = Invoice.model_validate(normalized.model_dump())
            else:
                normalized = ReceiveNote.model_validate(normalized.model_dump())
            latency_ms = round((perf_counter() - started) * 1000)
            self._run_repository.complete(
                run_id,
                raw_output=result.raw_output,
                normalized_output=normalized.model_dump(mode="json"),
                latency_ms=latency_ms,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                estimated_cost_aud=(
                    str(result.estimated_cost_aud)
                    if result.estimated_cost_aud is not None
                    else None
                ),
            )
            self._task_repository.update_status(
                task.task_id,
                ExtractionStatus.READY_FOR_REVIEW,
            )
        except Exception as exc:
            message = str(exc)[:2000] or exc.__class__.__name__
            self._run_repository.fail(run_id, message)
            self._task_repository.update_status(
                task.task_id,
                ExtractionStatus.FAILED,
                error_message=message,
            )

    def get_run(self, run_id: str) -> ExtractionRun:
        """读取 Run，并把 Repository 的 None 转成稳定领域错误。"""

        run = self._run_repository.get(run_id)
        if run is None:
            raise ExtractionRunNotFound(run_id)
        return run

    def cancel(self, run_id: str, *, requested_by: str) -> ExtractionRun:
        """请求协作式取消；已进入终态或审核阶段的 Run 不允许取消。"""

        current = self.get_run(run_id)
        cancellable = {
            ExtractionRunStatus.QUEUED,
            ExtractionRunStatus.SUBMITTING,
            ExtractionRunStatus.PARSING,
            ExtractionRunStatus.NORMALIZING,
            ExtractionRunStatus.VALIDATING,
            ExtractionRunStatus.CANCELLED,
        }
        if current.status not in cancellable:
            raise ExtractionStateConflict(
                f"Run in status '{current.status}' cannot be cancelled"
            )
        result = self._run_repository.request_cancel(
            run_id,
            requested_by=requested_by,
            requested_at=datetime.now(UTC),
        )
        if result is None:
            raise ExtractionRunNotFound(run_id)
        if result.status == ExtractionRunStatus.CANCELLED:
            self._task_repository.update_status(
                result.task_id,
                ExtractionStatus.CANCELLED,
            )
        return result
