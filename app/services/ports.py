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
    def create(self, run: ExtractionRun) -> None: ...

    def get(self, run_id: str) -> ExtractionRun | None: ...

    def get_latest_for_task(self, task_id: str) -> ExtractionRun | None: ...

    def claim_next(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
        now: datetime,
    ) -> ExtractionRun | None: ...

    def set_remote_job(
        self,
        run_id: str,
        *,
        remote_job_id: str,
        next_attempt_at: datetime,
    ) -> None: ...

    def schedule_poll(
        self,
        run_id: str,
        *,
        next_attempt_at: datetime,
        increment_attempt: bool = False,
    ) -> None: ...

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
    ) -> None: ...

    def set_model_provenance(
        self,
        run_id: str,
        *,
        parser_provider: str,
        parser_model: str,
        normalizer_provider: str,
        normalizer_model: str,
        prompt_version: str,
    ) -> None: ...

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
    ) -> None: ...

    def request_cancel(
        self,
        run_id: str,
        *,
        requested_by: str,
        requested_at: datetime,
    ) -> ExtractionRun | None: ...

    def is_cancel_requested(self, run_id: str) -> bool: ...

    def mark_cancelled(
        self,
        run_id: str,
        *,
        stage: str,
        remote_may_continue: bool,
    ) -> ExtractionRun | None: ...


class ParseResultRepository(Protocol):
    def create(self, result: ParseResultRecord) -> None: ...

    def get_for_run(self, run_id: str) -> ParseResultRecord | None: ...


class DocumentDraftRepository(Protocol):
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
    def heartbeat(
        self,
        *,
        worker_id: str,
        version: str,
        now: datetime,
    ) -> None: ...

    def latest(self) -> WorkerHeartbeat | None: ...
