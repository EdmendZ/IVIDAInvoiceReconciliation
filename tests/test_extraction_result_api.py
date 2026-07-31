from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.api.dependencies import (
    get_draft_repository,
    get_extraction_service,
    get_parse_repository,
)
from app.domain.document_drafts import DocumentDraft, DraftValidationState
from app.domain.documents import DocumentType
from app.domain.extraction_runs import ExtractionRun, ExtractionRunStatus
from app.domain.normalization import FieldEvidence
from app.domain.parse_results import ParseResultRecord
from app.main import app
from app.services.extraction_provider import DisabledExtractionProvider
from app.services.extraction_service import ExtractionService
from tests.auth_helpers import reviewer_client
from tests.fakes import (
    InMemoryDocumentDraftRepository,
    InMemoryExtractionRunRepository,
    InMemoryExtractionTaskRepository,
    InMemoryObjectStorage,
    InMemoryParseResultRepository,
)


def test_result_api_returns_draft_evidence_and_disables_approval() -> None:
    now = datetime.now(UTC)
    runs = InMemoryExtractionRunRepository()
    parses = InMemoryParseResultRepository()
    drafts = InMemoryDocumentDraftRepository()
    run = ExtractionRun(
        run_id="00000000-0000-0000-0000-000000000001",
        task_id="00000000-0000-0000-0000-000000000002",
        provider="mineru",
        model_name="vlm",
        status=ExtractionRunStatus.READY_FOR_REVIEW,
        started_at=now,
        completed_at=now,
        created_at=now,
    )
    runs.create(run)
    parses.create(
        ParseResultRecord(
            parse_result_id="00000000-0000-0000-0000-000000000003",
            run_id=run.run_id,
            remote_job_id="batch-1",
            artifact_object_key="invoice/result.zip",
            markdown="# TAX INVOICE",
            page_count=1,
            created_at=now,
        )
    )
    drafts.create_with_evidence_and_issues(
        DocumentDraft(
            draft_id="00000000-0000-0000-0000-000000000004",
            run_id=run.run_id,
            task_id=run.task_id,
            document_type=DocumentType.INVOICE,
            normalized_json={"document_number": "SCF-INV-260701"},
            validation_state=DraftValidationState.REVIEWABLE,
            created_at=now,
            updated_at=now,
        ),
        [
            FieldEvidence(
                field_path="document_number",
                value="SCF-INV-260701",
                page=1,
                source_text="Invoice SCF-INV-260701",
            )
        ],
        [],
    )
    service = ExtractionService(
        storage=InMemoryObjectStorage(),
        task_repository=InMemoryExtractionTaskRepository(),
        run_repository=runs,
        provider=DisabledExtractionProvider(),
    )
    app.dependency_overrides[get_extraction_service] = lambda: service
    app.dependency_overrides[get_parse_repository] = lambda: parses
    app.dependency_overrides[get_draft_repository] = lambda: drafts
    try:
        with reviewer_client(app) as client:
            response = client.get(
                f"/api/extraction-runs/{run.run_id}/result"
            )
            assert response.status_code == 200
            body = response.json()
            assert body["draft"]["document_number"] == "SCF-INV-260701"
            assert body["evidence"][0]["field_path"] == "document_number"
            assert body["approval_allowed"] is False
    finally:
        app.dependency_overrides.clear()
