from datetime import UTC, datetime
from decimal import Decimal

from app.domain.extraction_runs import ExtractionRun, ExtractionRunStatus
from app.domain.extraction_tasks import ExtractionStatus
from app.domain.extraction_tasks import ExtractionTask
from app.domain.parse_results import ParseResultRecord
from app.domain.document_drafts import DocumentDraft, DraftBundle
from app.domain.normalization import FieldEvidence
from app.domain.validation import ValidationIssue


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

    def list_recent(self, limit: int = 100) -> list[ExtractionTask]:
        return sorted(
            self.tasks.values(),
            key=lambda item: item.created_at,
            reverse=True,
        )[:limit]

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

    def get_latest_for_task(self, task_id: str) -> ExtractionRun | None:
        candidates = [
            run for run in self.runs.values() if run.task_id == task_id
        ]
        if not candidates:
            return None
        return sorted(
            candidates,
            key=lambda item: item.created_at,
            reverse=True,
        )[0]

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

    def mark_ready_for_review(
        self,
        run_id: str,
        *,
        normalized_output: dict,
        input_tokens: int | None,
        output_tokens: int | None,
        estimated_cost_aud: str | None,
    ) -> None:
        self.runs[run_id] = self.runs[run_id].model_copy(
            update={
                "status": ExtractionRunStatus.READY_FOR_REVIEW,
                "normalized_output": normalized_output,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "estimated_cost_aud": (
                    Decimal(estimated_cost_aud)
                    if estimated_cost_aud is not None
                    else None
                ),
                "completed_at": datetime.now(UTC),
                "lease_owner": None,
            }
        )

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

    def request_cancel(
        self,
        run_id: str,
        *,
        requested_by: str,
        requested_at: datetime,
    ) -> ExtractionRun | None:
        run = self.runs.get(run_id)
        if run is None:
            return None
        changes = {
            "cancel_requested_at": run.cancel_requested_at or requested_at,
            "cancel_requested_by": run.cancel_requested_by or requested_by,
        }
        if run.status == ExtractionRunStatus.QUEUED:
            changes.update(
                status=ExtractionRunStatus.CANCELLED,
                cancel_completed_at=requested_at,
                cancelled_stage=ExtractionRunStatus.QUEUED.value,
                completed_at=requested_at,
                lease_owner=None,
            )
        updated = run.model_copy(update=changes)
        self.runs[run_id] = updated
        return updated

    def is_cancel_requested(self, run_id: str) -> bool:
        run = self.runs.get(run_id)
        return bool(run and run.cancel_requested_at is not None)

    def mark_cancelled(
        self,
        run_id: str,
        *,
        stage: str,
        remote_may_continue: bool,
    ) -> ExtractionRun | None:
        run = self.runs.get(run_id)
        if run is None:
            return None
        now = datetime.now(UTC)
        updated = run.model_copy(
            update={
                "status": ExtractionRunStatus.CANCELLED,
                "cancel_completed_at": now,
                "cancelled_stage": stage,
                "remote_may_continue": remote_may_continue,
                "completed_at": now,
                "lease_owner": None,
            }
        )
        self.runs[run_id] = updated
        return updated


class InMemoryParseResultRepository:
    def __init__(self) -> None:
        self.results: dict[str, ParseResultRecord] = {}

    def create(self, result: ParseResultRecord) -> None:
        self.results[result.run_id] = result

    def get_for_run(self, run_id: str) -> ParseResultRecord | None:
        return self.results.get(run_id)


class InMemoryDocumentDraftRepository:
    def __init__(self) -> None:
        self.bundles: dict[str, DraftBundle] = {}

    def create_with_evidence_and_issues(
        self,
        draft: DocumentDraft,
        evidence: list[FieldEvidence],
        issues: list[ValidationIssue],
    ) -> DocumentDraft:
        self.bundles[draft.run_id] = DraftBundle(
            draft=draft,
            evidence=evidence,
            issues=issues,
        )
        return draft

    def get_for_run(self, run_id: str) -> DraftBundle | None:
        return self.bundles.get(run_id)

    def get_for_task(self, task_id: str) -> DraftBundle | None:
        candidates = [
            bundle
            for bundle in self.bundles.values()
            if bundle.draft.task_id == task_id
        ]
        if not candidates:
            return None
        return sorted(
            candidates,
            key=lambda item: item.draft.created_at,
            reverse=True,
        )[0]

    def list_latest(self) -> list[DraftBundle]:
        task_ids = {
            bundle.draft.task_id for bundle in self.bundles.values()
        }
        return [
            bundle
            for task_id in task_ids
            if (bundle := self.get_for_task(task_id)) is not None
        ]
