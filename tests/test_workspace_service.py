import csv
import hashlib
import io
import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.domain.admin_users import AdminRole, AuthenticatedUser
from app.domain.documents import DocumentType
from app.domain.workspace import (
    CachedResponse,
    ConfirmationPage,
    ConfirmationQuery,
    ConfirmationSummary,
    ConfirmationView,
    Coverage,
    DisplayStatus,
    DocumentSummary,
    IntakeResponse,
    LineResult,
    LineStatus,
    MetricComparison,
    MetricStatus,
    PreviewOutcome,
    PreviewResult,
    PreviewSummary,
    ProcessingStatus,
    Resolution,
    SourceKind,
    SourceMetadata,
    SubjectComparison,
    UploadCommand,
    WorkspaceError,
    WorkspaceErrorCode,
    WorkspaceScopeKey,
)
from app.services.document_upload_service import DocumentUploadService
from app.services.workspace_service import WorkspaceService
from tests.fakes import InMemoryExtractionTaskRepository, InMemoryObjectStorage


def uid(number: int) -> str:
    return f"00000000-0000-0000-0000-{number:012d}"


def summary(number: int = 10) -> DocumentSummary:
    return DocumentSummary(
        document_id=uid(number),
        document_type=DocumentType.INVOICE,
        source_kind=SourceKind.UPLOAD,
        revision=1,
        processing_status=ProcessingStatus.PROCESSING,
        display_status=DisplayStatus.PROCESSING,
        updated_at=datetime(2026, 9, 16, tzinfo=UTC),
    )


def intake(*, task_id: str, duplicate: bool) -> IntakeResponse:
    return IntakeResponse(
        document=summary(), task_id=task_id, run_id=uid(12), duplicate=duplicate
    )


def confirmation() -> ConfirmationView:
    def metric(left, right, difference, status):
        return MetricComparison(
            invoice_value=left,
            received_value=right,
            difference=difference,
            status=status,
        )

    return ConfirmationView(
        confirmation_id=uid(20),
        preview_id=uid(21),
        invoice_number="=INVOICE()",
        receive_note_numbers=["+RN-1", "RN-2"],
        resolution=Resolution.RESOLVED_WITH_NOTE,
        note="@resolved",
        acknowledged_unverified_dimensions=["document_total", "tax"],
        result_snapshot=PreviewResult(
            outcome=PreviewOutcome.DIFFERENCE,
            coverage=Coverage.FULL,
            unverified_dimensions=["document_total", "tax"],
            lines=[
                LineResult(
                    match_key="=SKU",
                    sku="+SKU",
                    description="\tDanger",
                    invoice_unit="each",
                    received_unit="each",
                    quantity=metric(
                        Decimal("2"),
                        Decimal("3"),
                        Decimal("-1"),
                        MetricStatus.DIFFERENT,
                    ),
                    price=metric(
                        Decimal("1.00"),
                        Decimal("1.00"),
                        Decimal("0.00"),
                        MetricStatus.EQUAL,
                    ),
                    amount=metric(
                        Decimal("2.00"),
                        Decimal("3.00"),
                        Decimal("-1.00"),
                        MetricStatus.DIFFERENT,
                    ),
                    status=LineStatus.DIFFERENT,
                )
            ],
            summary=PreviewSummary(
                total_lines=1, different_lines=1, unverified_lines=0
            ),
            subject=SubjectComparison(
                supplier="equal", currency="equal", scope="equal"
            ),
        ),
        input_revision_ids=[uid(22), uid(23), uid(24)],
        actor_id=uid(1),
        created_at=datetime(2026, 9, 16, tzinfo=UTC),
    )


class RecordingRepository:
    def __init__(self) -> None:
        self.cached = None
        self.intake_response = None
        self.intake_error = None
        self.calls = []
        self.confirmation = confirmation()

    def cached_request(self, *args):
        self.calls.append(("cached_request", args))
        return self.cached

    def intake(self, *args):
        self.calls.append(("intake", args))
        if self.intake_error:
            raise self.intake_error
        return self.intake_response

    def mutate(self, *args):
        self.calls.append(("mutate", args))
        return summary()

    def source_metadata(self, *args):
        self.calls.append(("source_metadata", args))
        return SourceMetadata(
            filename="invoice.pdf",
            content_type="application/pdf",
            object_key="invoice/source",
        )

    def get_confirmation(self, *args):
        self.calls.append(("get_confirmation", args))
        return self.confirmation

    def list_confirmations(self, *args):
        self.calls.append(("list_confirmations", args))
        return ConfirmationPage(
            items=[ConfirmationSummary(
                confirmation_id=self.confirmation.confirmation_id,
                invoice_document_id=uid(10),
                invoice_number=self.confirmation.invoice_number,
                supplier_name="Fresh Foods Pty Ltd",
                receive_note_numbers=self.confirmation.receive_note_numbers,
                resolution=self.confirmation.resolution,
                outcome=self.confirmation.result_snapshot.outcome,
                coverage=self.confirmation.result_snapshot.coverage,
                acknowledged_unverified_dimensions=self.confirmation.acknowledged_unverified_dimensions,
                note=self.confirmation.note,
                actor_id=self.confirmation.actor_id,
                created_at=self.confirmation.created_at,
            )],
            page=1,
            page_size=20,
            total=1,
        )

    def list_documents(self, *args):
        self.calls.append(("list_documents", args))

    def get_document(self, *args):
        self.calls.append(("get_document", args))

    def get_actions(self, *args):
        self.calls.append(("get_actions", args))

    def runtime(self, *args):
        self.calls.append(("runtime", args))


def make_service(repository=None, storage=None):
    repository = repository or RecordingRepository()
    storage = storage or InMemoryObjectStorage()
    uploads = DocumentUploadService(
        storage, InMemoryExtractionTaskRepository(), max_bytes=1024
    )
    service = WorkspaceService(
        repository,
        uploads,
        storage,
        WorkspaceScopeKey(tenant_id="tenant", store_id="store"),
    )
    return service, repository, storage


ACTOR = AuthenticatedUser(
    user_id=uid(1), username="reviewer", role=AdminRole.REVIEWER
)


def test_upload_checks_cache_before_writing_an_object() -> None:
    service, repository, storage = make_service()
    response = intake(task_id=uid(30), duplicate=False)
    repository.cached = CachedResponse(status=201, body=response.model_dump(mode="json"))

    actual = service.upload(
        UploadCommand(
            document_type=DocumentType.INVOICE,
            filename="Original Name.pdf",
            data=b"%PDF-1.7 invoice",
        ),
        ACTOR,
        uid(31),
    )

    assert actual == response
    assert [call[0] for call in repository.calls] == ["cached_request"]
    assert storage.objects == {}


def test_upload_hash_uses_type_content_hash_and_original_filename() -> None:
    service, repository, storage = make_service()
    repository.intake_response = intake(task_id=uid(30), duplicate=True)
    data = b"%PDF-1.7 invoice"

    service.upload(
        UploadCommand(
            document_type=DocumentType.INVOICE,
            filename="Original Name.pdf",
            data=data,
        ),
        ACTOR,
        uid(31),
    )

    body = json.dumps(
        {
            "document_type": "invoice",
            "file_sha256": hashlib.sha256(data).hexdigest(),
            "filename": "Original Name.pdf",
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    expected = hashlib.sha256(
        f"POST/api/workspace/documents{body}".encode("utf-8")
    ).hexdigest()
    assert repository.calls[0][1][-1] == expected
    assert repository.calls[1][1][-1] == expected
    assert storage.objects == {}


def test_upload_cleanup_never_masks_the_intake_error() -> None:
    class FailingCleanupStorage(InMemoryObjectStorage):
        def delete(self, object_key: str) -> None:
            raise OSError("cleanup failed")

    repository = RecordingRepository()
    repository.intake_error = WorkspaceError(
        WorkspaceErrorCode.IDEMPOTENCY_CONFLICT,
        "请求标识已用于不同操作",
    )
    service, _, _ = make_service(repository, FailingCleanupStorage())

    with pytest.raises(WorkspaceError) as captured:
        service.upload(
            UploadCommand(
                document_type=DocumentType.INVOICE,
                filename="invoice.pdf",
                data=b"%PDF-1.7 invoice",
            ),
            ACTOR,
            uid(31),
        )

    assert captured.value.detail.code == WorkspaceErrorCode.IDEMPOTENCY_CONFLICT


def test_mutation_hash_contains_method_path_and_canonical_body() -> None:
    from app.domain.workspace import InvestigateCommand

    service, repository, _ = make_service()
    command = InvestigateCommand(expected_revision=7, note="需要核实")

    service.investigate(uid(10), command, ACTOR, uid(31))

    call = repository.calls[-1]
    assert call[0] == "mutate"
    body = json.dumps(
        command.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    expected = hashlib.sha256(
        f"POST/api/workspace/documents/{uid(10)}/investigate{body}".encode(
            "utf-8"
        )
    ).hexdigest()
    assert call[1][2].value == "investigate"
    assert call[1][-1] == expected


def test_source_reads_only_repository_authorized_metadata() -> None:
    service, repository, storage = make_service()
    storage.put("invoice/source", b"%PDF-1.7 invoice", "application/pdf")

    source = service.source(uid(10))

    assert repository.calls[0][0] == "source_metadata"
    assert source.filename == "invoice.pdf"
    assert source.content_type == "application/pdf"
    assert source.data == b"%PDF-1.7 invoice"


def test_confirmation_history_query_delegates_with_scope() -> None:
    service, repository, _ = make_service()
    query = ConfirmationQuery(q="RN-1", outcome=["difference"], page=1, page_size=20)

    page = service.list_confirmations(query)

    assert page.total == 1
    assert repository.calls[-1][0] == "list_confirmations"
    assert repository.calls[-1][1][1] == query


def test_source_scope_failure_happens_before_storage_access() -> None:
    class ScopeRejectingRepository(RecordingRepository):
        def source_metadata(self, *args):
            raise WorkspaceError(
                WorkspaceErrorCode.DOCUMENT_NOT_FOUND,
                "未找到单据",
            )

    class RecordingStorage(InMemoryObjectStorage):
        def __init__(self) -> None:
            super().__init__()
            self.get_calls = []

        def get(self, object_key: str) -> bytes:
            self.get_calls.append(object_key)
            return super().get(object_key)

    storage = RecordingStorage()
    service, _, _ = make_service(ScopeRejectingRepository(), storage)

    with pytest.raises(WorkspaceError) as captured:
        service.source(uid(99))

    assert captured.value.detail.code == WorkspaceErrorCode.DOCUMENT_NOT_FOUND
    assert storage.get_calls == []


def test_csv_uses_confirmation_snapshot_and_escapes_formula_cells() -> None:
    service, _, _ = make_service()

    content = service.export(uid(20))
    rows = list(csv.reader(io.StringIO(content.lstrip("\ufeff"))))

    assert content.startswith("\ufeff")
    assert rows[0] == [
        "confirmation_id",
        "invoice_number",
        "receive_note_numbers",
        "rule_version",
        "resolution",
        "note",
        "match_key",
        "sku",
        "description",
        "invoice_quantity",
        "received_quantity",
        "quantity_difference",
        "quantity_status",
        "price_status",
        "amount_status",
    ]
    assert rows[1][1:6] == [
        "'=INVOICE()",
        "'+RN-1, RN-2",
        "ir-simple-rules-1",
        "resolved_with_note",
        "'@resolved",
    ]
    assert rows[1][6:9] == ["'=SKU", "'+SKU", "'\tDanger"]
    assert rows[1][9:12] == ["2", "3", "-1"]
