from datetime import UTC, datetime
from decimal import Decimal

from app.domain.extraction_runs import ExtractionRun, ExtractionRunStatus
from app.domain.extraction_tasks import ExtractionStatus
from app.domain.extraction_tasks import ExtractionTask
from app.domain.parse_results import ParseResultRecord


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

    def get(self, object_key: str) -> bytes:
        return self.objects[object_key][0]


class InMemoryExtractionTaskRepository:
    def __init__(self) -> None:
        self.tasks: dict[str, ExtractionTask] = {}

    def create(self, task: ExtractionTask) -> None:
        self.tasks[task.task_id] = task

    def get(self, task_id: str) -> ExtractionTask | None:
        return self.tasks.get(task_id)

    def update_status(
        self,
        task_id: str,
        status: ExtractionStatus,
        error_message: str | None = None,
    ) -> None:
        task = self.tasks[task_id]
        self.tasks[task_id] = task.model_copy(
            update={
                "status": status,
                "error_message": error_message,
                "updated_at": datetime.now(UTC),
            }
        )


class InMemoryExtractionRunRepository:
    def __init__(self) -> None:
        self.runs: dict[str, ExtractionRun] = {}

    def create(self, run: ExtractionRun) -> None:
        self.runs[run.run_id] = run

    def get(self, run_id: str) -> ExtractionRun | None:
        return self.runs.get(run_id)

    def claim_next(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
        now: datetime,
    ) -> ExtractionRun | None:
        del lease_seconds
        eligible = {
            ExtractionRunStatus.QUEUED,
            ExtractionRunStatus.PARSING,
            ExtractionRunStatus.NORMALIZING,
            ExtractionRunStatus.VALIDATING,
        }
        candidates = [
            run
            for run in self.runs.values()
            if run.status in eligible
            and (run.next_attempt_at is None or run.next_attempt_at <= now)
            and (run.lease_expires_at is None or run.lease_expires_at < now)
        ]
        if not candidates:
            return None
        run = sorted(candidates, key=lambda item: item.created_at)[0]
        claimed = run.model_copy(update={"lease_owner": worker_id})
        self.runs[run.run_id] = claimed
        return claimed

    def set_remote_job(
        self,
        run_id: str,
        *,
        remote_job_id: str,
        next_attempt_at: datetime,
    ) -> None:
        self.runs[run_id] = self.runs[run_id].model_copy(
            update={
                "status": ExtractionRunStatus.PARSING,
                "remote_job_id": remote_job_id,
                "next_attempt_at": next_attempt_at,
                "lease_owner": None,
            }
        )

    def schedule_poll(
        self,
        run_id: str,
        *,
        next_attempt_at: datetime,
        increment_attempt: bool = False,
    ) -> None:
        run = self.runs[run_id]
        self.runs[run_id] = run.model_copy(
            update={
                "status": ExtractionRunStatus.PARSING,
                "next_attempt_at": next_attempt_at,
                "attempt_count": run.attempt_count + int(increment_attempt),
                "lease_owner": None,
            }
        )

    def set_status(
        self,
        run_id: str,
        status: ExtractionRunStatus,
        *,
        release_lease: bool = True,
    ) -> None:
        changes = {"status": status}
        if release_lease:
            changes["lease_owner"] = None
        self.runs[run_id] = self.runs[run_id].model_copy(update=changes)

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
    ) -> None:
        self.runs[run_id] = self.runs[run_id].model_copy(
            update={
                "status": ExtractionRunStatus.SUCCEEDED,
                "raw_output": raw_output,
                "normalized_output": normalized_output,
                "latency_ms": latency_ms,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "estimated_cost_aud": (
                    Decimal(estimated_cost_aud)
                    if estimated_cost_aud is not None
                    else None
                ),
                "completed_at": datetime.now(UTC),
                "error_message": None,
            }
        )

    def fail(
        self,
        run_id: str,
        error_message: str,
        *,
        error_code: str | None = None,
    ) -> None:
        self.runs[run_id] = self.runs[run_id].model_copy(
            update={
                "status": ExtractionRunStatus.FAILED,
                "error_message": error_message,
                "phase_error_code": error_code,
                "completed_at": datetime.now(UTC),
                "lease_owner": None,
            }
        )


class InMemoryParseResultRepository:
    def __init__(self) -> None:
        self.results: dict[str, ParseResultRecord] = {}

    def create(self, result: ParseResultRecord) -> None:
        self.results[result.run_id] = result

    def get_for_run(self, run_id: str) -> ParseResultRecord | None:
        return self.results.get(run_id)
