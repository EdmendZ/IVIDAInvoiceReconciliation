from datetime import UTC, datetime, timedelta

from app.domain.documents import DocumentType
from app.domain.extraction_runs import ExtractionRunStatus
from app.domain.parsing import (
    ParserPollResult,
    ParserSubmission,
    ParseResult,
    ParseState,
)
from app.services.document_upload_service import DocumentUploadService
from app.services.extraction_provider import DisabledExtractionProvider
from app.services.extraction_service import ExtractionService
from app.workers.extraction_worker import ExtractionWorker
from tests.fakes import (
    InMemoryExtractionRunRepository,
    InMemoryExtractionTaskRepository,
    InMemoryObjectStorage,
    InMemoryParseResultRepository,
)


class FakeParser:
    provider_name = "mineru"
    model_name = "vlm"

    def __init__(self) -> None:
        self.submit_count = 0

    def submit(self, **kwargs) -> ParserSubmission:
        self.submit_count += 1
        return ParserSubmission(remote_job_id="batch-123")

    def poll(self, remote_job_id: str) -> ParserPollResult:
        return ParserPollResult(
            state=ParseState.SUCCEEDED,
            progress=100,
            result=ParseResult(
                provider="mineru",
                model_name="vlm",
                remote_task_id="task-456",
                markdown="# TAX INVOICE",
                content_blocks=[{"type": "text", "page_idx": 0}],
                tables=[],
                page_count=1,
                artifact_archive=b"zip-data",
            ),
        )


def test_worker_submits_then_polls_and_persists_result() -> None:
    storage = InMemoryObjectStorage()
    tasks = InMemoryExtractionTaskRepository()
    runs = InMemoryExtractionRunRepository()
    parses = InMemoryParseResultRepository()
    parser = FakeParser()
    upload = DocumentUploadService(storage, tasks, max_bytes=1024)
    task = upload.upload(
        DocumentType.INVOICE,
        "invoice.pdf",
        b"%PDF-1.7 fixture",
    )
    service = ExtractionService(
        storage=storage,
        task_repository=tasks,
        run_repository=runs,
        provider=DisabledExtractionProvider(),
    )
    run = service.queue(task.task_id)
    worker = ExtractionWorker(
        parser=parser,
        storage=storage,
        task_repository=tasks,
        run_repository=runs,
        parse_repository=parses,
        poll_interval_seconds=0,
    )

    assert worker.run_once("worker-1") is True
    submitted = runs.get(run.run_id)
    assert submitted is not None
    assert submitted.status == ExtractionRunStatus.PARSING
    assert submitted.remote_job_id == "batch-123"
    assert parser.submit_count == 1

    assert worker.run_once("worker-1") is True
    persisted = parses.get_for_run(run.run_id)
    assert persisted is not None
    assert persisted.remote_job_id == "batch-123"
    assert storage.get(persisted.artifact_object_key) == b"zip-data"
    assert runs.get(run.run_id).status == ExtractionRunStatus.NORMALIZING
