from app.domain.documents import DocumentType
from app.domain.extraction_runs import ExtractionRunStatus
from app.domain.extraction_tasks import ExtractionStatus
from app.services.document_upload_service import DocumentUploadService
from app.services.extraction_provider import DisabledExtractionProvider
from app.services.extraction_service import ExtractionService
from app.services.validation_service import ValidationService
from app.workers.extraction_worker import ExtractionWorker
from tests.fakes import (
    InMemoryDocumentDraftRepository,
    InMemoryExtractionRunRepository,
    InMemoryExtractionTaskRepository,
    InMemoryObjectStorage,
    InMemoryParseResultRepository,
)
from tests.test_extraction_worker import FakeNormalizer, FakeParser


def _fixture():
    storage = InMemoryObjectStorage()
    tasks = InMemoryExtractionTaskRepository()
    runs = InMemoryExtractionRunRepository()
    parses = InMemoryParseResultRepository()
    drafts = InMemoryDocumentDraftRepository()
    task = DocumentUploadService(storage, tasks, max_bytes=1024).upload(
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
        parser=FakeParser(),
        storage=storage,
        task_repository=tasks,
        run_repository=runs,
        parse_repository=parses,
        normalizer=FakeNormalizer(),
        draft_repository=drafts,
        validation_service=ValidationService(),
        poll_interval_seconds=0,
    )
    return service, worker, tasks, runs, drafts, task, run


def test_queued_run_cancels_immediately_and_idempotently() -> None:
    service, _, tasks, _, _, task, run = _fixture()

    first = service.cancel(run.run_id, requested_by="reviewer-1")
    second = service.cancel(run.run_id, requested_by="reviewer-1")

    assert first.status == ExtractionRunStatus.CANCELLED
    assert second.status == ExtractionRunStatus.CANCELLED
    assert first.cancel_requested_by == "reviewer-1"
    assert first.cancel_completed_at is not None
    assert tasks.get(task.task_id).status == ExtractionStatus.CANCELLED


def test_parsing_run_stops_before_poll_and_never_creates_draft() -> None:
    service, worker, tasks, runs, drafts, task, run = _fixture()
    assert worker.run_once("worker-1") is True
    assert runs.get(run.run_id).status == ExtractionRunStatus.PARSING

    requested = service.cancel(run.run_id, requested_by="reviewer-1")
    assert requested.status == ExtractionRunStatus.PARSING
    assert requested.cancel_requested_at is not None

    assert worker.run_once("worker-1") is True

    cancelled = runs.get(run.run_id)
    assert cancelled.status == ExtractionRunStatus.CANCELLED
    assert cancelled.remote_may_continue is True
    assert cancelled.cancelled_stage == "parsing"
    assert drafts.get_for_run(run.run_id) is None
    assert tasks.get(task.task_id).status == ExtractionStatus.CANCELLED
