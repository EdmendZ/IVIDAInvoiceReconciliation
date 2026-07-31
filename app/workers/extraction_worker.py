from __future__ import annotations

import logging
import threading
import time
from time import perf_counter
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.domain.extraction_runs import ExtractionRun, ExtractionRunStatus
from app.domain.extraction_tasks import ExtractionStatus
from app.domain.document_drafts import DocumentDraft, DraftValidationState
from app.domain.parse_results import ParseResultRecord
from app.domain.parsing import AsyncDocumentParser, ParseResult, ParseState
from app.domain.normalization import NormalizationProvider
from app.infra.external_errors import ExternalServiceError
from app.services.ports import (
    ExtractionRunRepository,
    ExtractionTaskRepository,
    DocumentDraftRepository,
    ObjectStorage,
    ParseResultRepository,
    WorkerRuntimeRepository,
)
from app.services.validation_service import ValidationService

logger = logging.getLogger(__name__)


class ExtractionWorker:
    def __init__(
        self,
        *,
        parser: AsyncDocumentParser,
        storage: ObjectStorage,
        task_repository: ExtractionTaskRepository,
        run_repository: ExtractionRunRepository,
        parse_repository: ParseResultRepository,
        normalizer: NormalizationProvider | None = None,
        draft_repository: DocumentDraftRepository | None = None,
        validation_service: ValidationService | None = None,
        runtime_repository: WorkerRuntimeRepository | None = None,
        poll_interval_seconds: int = 5,
        lease_seconds: int = 60,
        heartbeat_interval_seconds: int = 10,
        worker_version: str = "0.1.0",
    ) -> None:
        self._parser = parser
        self._storage = storage
        self._task_repository = task_repository
        self._run_repository = run_repository
        self._parse_repository = parse_repository
        self._normalizer = normalizer
        self._draft_repository = draft_repository
        self._validation_service = validation_service
        self._runtime_repository = runtime_repository
        self._poll_interval_seconds = poll_interval_seconds
        self._lease_seconds = lease_seconds
        self._heartbeat_interval_seconds = heartbeat_interval_seconds
        self._worker_version = worker_version

    def run_once(self, worker_id: str) -> bool:
        now = datetime.now(UTC)
        run = self._run_repository.claim_next(
            worker_id=worker_id,
            lease_seconds=self._lease_seconds,
            now=now,
        )
        if run is None:
            return False
        try:
            if self._run_repository.is_cancel_requested(run.run_id):
                self._cancel_run(run, stage=run.status.value)
                return True
            if run.status == ExtractionRunStatus.QUEUED:
                self._submit(run, now)
            elif run.status == ExtractionRunStatus.PARSING:
                self._poll(run, now)
            elif run.status == ExtractionRunStatus.NORMALIZING:
                self._normalize(run, now)
            else:
                self._run_repository.set_status(
                    run.run_id,
                    run.status,
                    release_lease=True,
                )
            return True
        except ExternalServiceError as exc:
            self._handle_external_error(run, exc, now)
            return True
        except Exception:
            logger.exception(
                "Extraction worker failed for run_id=%s task_id=%s",
                run.run_id,
                run.task_id,
            )
            self._fail(
                run,
                code="EXTRACTION_INTERNAL_ERROR",
                message="Extraction worker encountered an internal error",
            )
            return True

    def run_forever(self, *, worker_id: str, idle_seconds: float = 2) -> None:
        stop_heartbeat = threading.Event()
        heartbeat_thread: threading.Thread | None = None
        if self._runtime_repository is not None:
            heartbeat_thread = threading.Thread(
                target=self._heartbeat_forever,
                args=(worker_id, stop_heartbeat),
                daemon=True,
                name="ivida-worker-heartbeat",
            )
            heartbeat_thread.start()
        try:
            while True:
                if not self.run_once(worker_id):
                    time.sleep(idle_seconds)
        finally:
            stop_heartbeat.set()
            if heartbeat_thread is not None:
                heartbeat_thread.join(timeout=2)

    def record_heartbeat(self, worker_id: str) -> None:
        if self._runtime_repository is None:
            return
        self._runtime_repository.heartbeat(
            worker_id=worker_id,
            version=self._worker_version,
            now=datetime.now(UTC),
        )

    def _heartbeat_forever(
        self,
        worker_id: str,
        stop: threading.Event,
    ) -> None:
        while not stop.is_set():
            try:
                self.record_heartbeat(worker_id)
            except Exception:
                logger.exception(
                    "WORKER_HEARTBEAT_FAILED worker_id=%s",
                    worker_id,
                )
            stop.wait(self._heartbeat_interval_seconds)

    def _submit(self, run: ExtractionRun, now: datetime) -> None:
        task = self._task_repository.get(run.task_id)
        if task is None:
            self._fail(
                run,
                code="TASK_NOT_FOUND",
                message="Extraction task no longer exists",
            )
            return
        content = self._storage.get(task.storage_object_key)
        submission = self._parser.submit(
            filename=task.original_filename,
            content_type=task.content_type,
            content=content,
        )
        self._run_repository.set_remote_job(
            run.run_id,
            remote_job_id=submission.remote_job_id,
            next_attempt_at=now + timedelta(seconds=self._poll_interval_seconds),
        )
        if self._run_repository.is_cancel_requested(run.run_id):
            self._cancel_run(
                run,
                stage=ExtractionRunStatus.SUBMITTING.value,
                remote_may_continue=True,
            )

    def _poll(self, run: ExtractionRun, now: datetime) -> None:
        if not run.remote_job_id:
            self._fail(
                run,
                code="REMOTE_JOB_MISSING",
                message="MinerU remote job ID is missing",
            )
            return
        poll_result = self._parser.poll(run.remote_job_id)
        if self._run_repository.is_cancel_requested(run.run_id):
            self._cancel_run(
                run,
                stage=ExtractionRunStatus.PARSING.value,
                remote_may_continue=True,
            )
            return
        if poll_result.state in {ParseState.QUEUED, ParseState.RUNNING}:
            self._run_repository.schedule_poll(
                run.run_id,
                next_attempt_at=now
                + timedelta(seconds=self._poll_interval_seconds),
            )
            return
        if poll_result.state == ParseState.FAILED or poll_result.result is None:
            self._fail(
                run,
                code=poll_result.error_code or "MINERU_PARSE_FAILED",
                message=poll_result.error_message
                or "MinerU could not parse the document",
            )
            return

        task = self._task_repository.get(run.task_id)
        if task is None:
            self._fail(
                run,
                code="TASK_NOT_FOUND",
                message="Extraction task no longer exists",
            )
            return
        result = poll_result.result
        artifact_key = (
            f"{task.document_type.value}/{task.task_id}/runs/{run.run_id}/"
            "mineru/result.zip"
        )
        self._storage.put(
            artifact_key,
            result.artifact_archive,
            "application/zip",
        )
        self._parse_repository.create(
            ParseResultRecord(
                parse_result_id=str(uuid4()),
                run_id=run.run_id,
                remote_job_id=run.remote_job_id,
                artifact_object_key=artifact_key,
                markdown=result.markdown,
                content_blocks=result.content_blocks,
                tables=result.tables,
                page_count=result.page_count,
                created_at=now,
            )
        )
        self._run_repository.set_status(
            run.run_id,
            ExtractionRunStatus.NORMALIZING,
        )

    def _normalize(self, run: ExtractionRun, now: datetime) -> None:
        if (
            self._normalizer is None
            or self._draft_repository is None
            or self._validation_service is None
        ):
            self._fail(
                run,
                code="NORMALIZATION_NOT_CONFIGURED",
                message="Document normalization is not configured",
            )
            return
        task = self._task_repository.get(run.task_id)
        record = self._parse_repository.get_for_run(run.run_id)
        if task is None or record is None:
            self._fail(
                run,
                code="PARSE_RESULT_MISSING",
                message="Persisted MinerU result is missing",
            )
            return
        parse_result = ParseResult(
            provider="mineru",
            model_name=self._parser.model_name,
            markdown=record.markdown,
            content_blocks=record.content_blocks,
            tables=record.tables,
            page_count=record.page_count,
        )
        self._run_repository.set_model_provenance(
            run.run_id,
            parser_provider=parse_result.provider,
            parser_model=parse_result.model_name,
            normalizer_provider=self._normalizer.provider_name,
            normalizer_model=self._normalizer.model_name,
            prompt_version=self._normalizer.prompt_version,
        )
        normalization_started = perf_counter()
        normalized = self._normalizer.normalize(
            document_type=task.document_type,
            parse_result=parse_result,
        )
        normalization_latency_ms = round(
            (perf_counter() - normalization_started) * 1000
        )
        if self._run_repository.is_cancel_requested(run.run_id):
            self._cancel_run(
                run,
                stage=ExtractionRunStatus.NORMALIZING.value,
                remote_may_continue=bool(run.remote_job_id),
            )
            return
        report = self._validation_service.validate(normalized.document)
        draft = DocumentDraft(
            draft_id=str(uuid4()),
            run_id=run.run_id,
            task_id=run.task_id,
            document_type=task.document_type,
            normalized_json=normalized.document.model_dump(mode="json"),
            validation_state=(
                DraftValidationState.BLOCKED
                if report.blocking_count
                else DraftValidationState.REVIEWABLE
            ),
            created_at=now,
            updated_at=now,
        )
        self._draft_repository.create_with_evidence_and_issues(
            draft,
            normalized.evidence,
            report.issues,
        )
        self._run_repository.mark_ready_for_review(
            run.run_id,
            normalized_output=draft.normalized_json,
            input_tokens=normalized.input_tokens,
            output_tokens=normalized.output_tokens,
            estimated_cost_aud=(
                str(normalized.estimated_cost_aud)
                if normalized.estimated_cost_aud is not None
                else None
            ),
            normalization_latency_ms=normalization_latency_ms,
        )
        self._task_repository.update_status(
            run.task_id,
            ExtractionStatus.READY_FOR_REVIEW,
        )

    def _handle_external_error(
        self,
        run: ExtractionRun,
        exc: ExternalServiceError,
        now: datetime,
    ) -> None:
        if not exc.retryable or run.attempt_count >= 3:
            self._fail(run, code=exc.code, message=exc.safe_message)
            return
        delay = min(60, 2 ** (run.attempt_count + 1))
        self._run_repository.schedule_poll(
            run.run_id,
            next_attempt_at=now + timedelta(seconds=delay),
            increment_attempt=True,
        )

    def _fail(self, run: ExtractionRun, *, code: str, message: str) -> None:
        self._run_repository.fail(
            run.run_id,
            message,
            error_code=code,
        )
        self._task_repository.update_status(
            run.task_id,
            ExtractionStatus.FAILED,
            error_message=message,
        )

    def _cancel_run(
        self,
        run: ExtractionRun,
        *,
        stage: str,
        remote_may_continue: bool | None = None,
    ) -> None:
        cancelled = self._run_repository.mark_cancelled(
            run.run_id,
            stage=stage,
            remote_may_continue=(
                bool(run.remote_job_id)
                if remote_may_continue is None
                else remote_may_continue
            ),
        )
        if cancelled is not None:
            self._task_repository.update_status(
                run.task_id,
                ExtractionStatus.CANCELLED,
            )
