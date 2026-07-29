from __future__ import annotations

import logging
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.domain.extraction_runs import ExtractionRun, ExtractionRunStatus
from app.domain.extraction_tasks import ExtractionStatus
from app.domain.parse_results import ParseResultRecord
from app.domain.parsing import AsyncDocumentParser, ParseState
from app.infra.external_errors import ExternalServiceError
from app.services.ports import (
    ExtractionRunRepository,
    ExtractionTaskRepository,
    ObjectStorage,
    ParseResultRepository,
)

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
        poll_interval_seconds: int = 5,
        lease_seconds: int = 60,
    ) -> None:
        self._parser = parser
        self._storage = storage
        self._task_repository = task_repository
        self._run_repository = run_repository
        self._parse_repository = parse_repository
        self._poll_interval_seconds = poll_interval_seconds
        self._lease_seconds = lease_seconds

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
            if run.status == ExtractionRunStatus.QUEUED:
                self._submit(run, now)
            elif run.status == ExtractionRunStatus.PARSING:
                self._poll(run, now)
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
        while True:
            if not self.run_once(worker_id):
                time.sleep(idle_seconds)

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

    def _poll(self, run: ExtractionRun, now: datetime) -> None:
        if not run.remote_job_id:
            self._fail(
                run,
                code="REMOTE_JOB_MISSING",
                message="MinerU remote job ID is missing",
            )
            return
        poll_result = self._parser.poll(run.remote_job_id)
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
