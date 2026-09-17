"""Create the deterministic, development-only workspace demonstration dataset."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.domain.admin_users import AdminRole, AuthenticatedUser
from app.domain.documents import DocumentType
from app.domain.workspace import UploadCommand, WorkspaceScopeKey
from app.infra.database import get_session_factory
from app.infra.database_models import (
    AdminUserRow,
    DocumentDraftRow,
    ExtractionRunRow,
    ExtractionTaskRow,
)
from app.infra.minio_storage import MinioObjectStorage
from app.infra.postgres_task_repository import PostgresExtractionTaskRepository
from app.infra.postgres_workspace_repository import PostgresWorkspaceRepository
from app.services.document_upload_service import DocumentUploadService
from app.services.workspace_service import WorkspaceService
from app.workers.workspace_worker import WorkspaceWorker


DEMO_FIXTURE_MARKER = "ir-simple-t13-demo-v1"
DEMO_ADMIN_USERNAME = "adminuser"


@dataclass(frozen=True)
class DemoDocument:
    key: str
    scenario: str
    filename: str
    document_type: DocumentType
    payload: dict[str, Any]


@dataclass(frozen=True)
class DemoScenarioResult:
    scenario: str
    document_ids: dict[str, str]
    display_status: str
    preview_outcome: str | None


@dataclass(frozen=True)
class DemoRuntime:
    session_factory: sessionmaker[Session]
    service: WorkspaceService
    repository: PostgresWorkspaceRepository
    worker: WorkspaceWorker
    actor: AuthenticatedUser


def _payload(
    kind: DocumentType,
    number: str,
    supplier: str,
    business_number: str,
    purchase_order: str,
    sku: str,
    description: str,
    quantity: str,
) -> dict[str, Any]:
    unit_price = 10
    return {
        "document_type": kind.value,
        "document_number": number,
        "document_date": "2026-09-17",
        "purchase_order_number": purchase_order,
        "currency": "AUD",
        "supplier": {
            "name": supplier,
            "business_number": business_number,
        },
        "location": {"name": "IVIDA Demo Store"},
        "subtotal": f"{int(quantity) * unit_price}.00",
        "tax_total": "0.00",
        "total": f"{int(quantity) * unit_price}.00",
        "items": [
            {
                "line_number": "1",
                "sku": sku,
                "description": description,
                "quantity": quantity,
                "unit": "case",
                "unit_price": "10.00",
                "tax_amount": "0.00",
                "line_total": f"{int(quantity) * unit_price}.00",
            }
        ],
    }


DEMO_DOCUMENTS = (
    DemoDocument(
        "invoice_waiting",
        "invoice_waiting_for_receive_note",
        "demo_invoice_waiting.pdf",
        DocumentType.INVOICE,
        _payload(
            DocumentType.INVOICE,
            "INV-DEMO-WAIT-001",
            "Harbour Bakery Supplies",
            "ABN-DEMO-1001",
            "PO-DEMO-WAIT-INV",
            "SKU-DEMO-FLOUR",
            "Premium Bakers Flour",
            "12",
        ),
    ),
    DemoDocument(
        "receive_note_waiting",
        "receive_note_waiting_for_invoice",
        "demo_receive_note_waiting.pdf",
        DocumentType.RECEIVE_NOTE,
        _payload(
            DocumentType.RECEIVE_NOTE,
            "RN-DEMO-WAIT-001",
            "Southern Dairy Goods",
            "ABN-DEMO-2002",
            "PO-DEMO-WAIT-RN",
            "SKU-DEMO-CHEESE",
            "Shredded Mozzarella",
            "7",
        ),
    ),
    DemoDocument(
        "consistent_invoice",
        "automatic_consistent",
        "demo_invoice_consistent.pdf",
        DocumentType.INVOICE,
        _payload(
            DocumentType.INVOICE,
            "INV-DEMO-MATCH-001",
            "Coastal Produce Market",
            "ABN-DEMO-3003",
            "PO-DEMO-MATCH",
            "SKU-DEMO-TOMATO",
            "Crushed Tomatoes",
            "10",
        ),
    ),
    DemoDocument(
        "consistent_receive_note",
        "automatic_consistent",
        "demo_receive_note_consistent.pdf",
        DocumentType.RECEIVE_NOTE,
        _payload(
            DocumentType.RECEIVE_NOTE,
            "RN-DEMO-MATCH-001",
            "Coastal Produce Market",
            "ABN-DEMO-3003",
            "PO-DEMO-MATCH",
            "SKU-DEMO-TOMATO",
            "Crushed Tomatoes",
            "10",
        ),
    ),
    DemoDocument(
        "difference_invoice",
        "automatic_quantity_difference",
        "demo_invoice_quantity_difference.pdf",
        DocumentType.INVOICE,
        _payload(
            DocumentType.INVOICE,
            "INV-DEMO-DIFF-001",
            "Outback Packaging Co",
            "ABN-DEMO-4004",
            "PO-DEMO-DIFF",
            "SKU-DEMO-BOX",
            "Pizza Delivery Boxes",
            "10",
        ),
    ),
    DemoDocument(
        "difference_receive_note",
        "automatic_quantity_difference",
        "demo_receive_note_quantity_difference.pdf",
        DocumentType.RECEIVE_NOTE,
        _payload(
            DocumentType.RECEIVE_NOTE,
            "RN-DEMO-DIFF-001",
            "Outback Packaging Co",
            "ABN-DEMO-4004",
            "PO-DEMO-DIFF",
            "SKU-DEMO-BOX",
            "Pizza Delivery Boxes",
            "8",
        ),
    ),
)


def ensure_development_environment(app_env: str) -> None:
    """Reject production before constructing database or object-storage clients."""

    if app_env.strip().casefold() in {"prod", "production"}:
        raise SystemExit("Demo data setup is disabled in production.")


def build_demo_pdf(document: DemoDocument) -> bytes:
    """Build a deterministic, one-page PDF containing the English fixture values."""

    item = document.payload["items"][0]
    supplier = document.payload["supplier"]
    lines = [
        "IVIDA DEVELOPMENT DEMO FIXTURE",
        f"Document: {document.payload['document_number']}",
        f"Type: {document.document_type.value}",
        f"Supplier: {supplier['name']}",
        f"Purchase Order: {document.payload['purchase_order_number']}",
        f"Item: {item['sku']} - {item['description']}",
        f"Quantity: {item['quantity']} {item['unit']}",
        f"Currency: {document.payload['currency']}",
        "This file bypasses OCR and model extraction for local demonstration only.",
    ]

    def escape(value: str) -> str:
        return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    commands = ["BT", "/F1 12 Tf", "50 790 Td"]
    for index, line in enumerate(lines):
        if index:
            commands.append("0 -22 Td")
        commands.append(f"({escape(line)}) Tj")
    commands.append("ET")
    stream = ("\n".join(commands) + "\n").encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 842] "
            b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
        ),
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"endstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    pdf = bytearray(b"%PDF-1.4\n%IVIDA-DEMO\n")
    offsets = [0]
    for number, body in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{number} 0 obj\n".encode("ascii"))
        pdf.extend(body)
        pdf.extend(b"\nendobj\n")
    xref_offset = len(pdf)
    pdf.extend(b"xref\n0 6\n0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    pdf.extend(
        b"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n"
        + str(xref_offset).encode("ascii")
        + b"\n%%EOF\n"
    )
    return bytes(pdf)


def _fixture_owned(run: ExtractionRunRow) -> bool:
    return bool(
        isinstance(run.raw_output, dict)
        and run.raw_output.get("fixture_kind") == DEMO_FIXTURE_MARKER
    )


def _persist_demo_draft(
    session_factory: sessionmaker[Session],
    document: DemoDocument,
    *,
    task_id: str,
    run_id: str,
    duplicate: bool,
    pdf_sha256: str,
) -> None:
    """Create exactly one marked Draft, refusing to alter non-demo extraction work."""

    with session_factory.begin() as session:
        task = session.get(ExtractionTaskRow, task_id)
        run = session.get(ExtractionRunRow, run_id)
        if task is None or run is None or run.task_id != task_id:
            raise RuntimeError("The workspace upload did not create the expected Task and Run.")
        if task.sha256 != pdf_sha256 or task.original_filename != document.filename:
            raise RuntimeError("Refusing to modify an upload that is not this demo fixture.")

        draft = session.scalar(
            select(DocumentDraftRow).where(DocumentDraftRow.run_id == run_id)
        )
        if draft is not None:
            if not _fixture_owned(run) or draft.normalized_json != document.payload:
                raise RuntimeError("Refusing to modify an existing non-demo Draft.")
            return
        if duplicate or _fixture_owned(run) or run.status != "queued":
            raise RuntimeError("Refusing to replace an existing non-demo extraction Run.")

        now = datetime.now(UTC)
        task.status = "ready_for_review"
        task.error_message = None
        task.updated_at = now
        run.provider = "demo_fixture"
        run.model_name = DEMO_FIXTURE_MARKER
        run.status = "ready_for_review"
        run.raw_output = {
            "fixture_kind": DEMO_FIXTURE_MARKER,
            "notice": "Local demo fixture; OCR and model extraction were bypassed.",
        }
        run.normalized_output = document.payload
        run.phase_error_code = None
        run.error_message = None
        run.next_attempt_at = None
        run.lease_owner = None
        run.lease_expires_at = None
        run.completed_at = now
        session.add(
            DocumentDraftRow(
                draft_id=str(uuid5(NAMESPACE_URL, f"{DEMO_FIXTURE_MARKER}:draft:{task_id}")),
                run_id=run_id,
                task_id=task_id,
                document_type=document.document_type.value,
                normalized_json=document.payload,
                validation_state="valid",
                created_at=now,
                updated_at=now,
            )
        )


def setup_demo_data(runtime: DemoRuntime) -> list[DemoScenarioResult]:
    """Upload six PDFs, persist marked fixture Drafts, and drive the real Worker."""

    intakes = {}
    for document in DEMO_DOCUMENTS:
        pdf = build_demo_pdf(document)
        intake = runtime.service.upload(
            UploadCommand(
                document_type=document.document_type,
                filename=document.filename,
                data=pdf,
            ),
            runtime.actor,
            str(uuid5(NAMESPACE_URL, f"{DEMO_FIXTURE_MARKER}:upload:{document.key}")),
        )
        _persist_demo_draft(
            runtime.session_factory,
            document,
            task_id=intake.task_id,
            run_id=intake.run_id,
            duplicate=intake.duplicate,
            pdf_sha256=hashlib.sha256(pdf).hexdigest(),
        )
        intakes[document.key] = intake

    tick = runtime.worker.tick()
    if tick.errors:
        raise RuntimeError(f"Workspace Worker reported {tick.errors} demo processing error(s).")

    scenarios = (
        ("invoice_waiting_for_receive_note", ("invoice_waiting",), "invoice_waiting"),
        ("receive_note_waiting_for_invoice", ("receive_note_waiting",), "receive_note_waiting"),
        ("automatic_consistent", ("consistent_invoice", "consistent_receive_note"), "consistent_invoice"),
        (
            "automatic_quantity_difference",
            ("difference_invoice", "difference_receive_note"),
            "difference_invoice",
        ),
    )
    expected = {
        "invoice_waiting_for_receive_note": ("waiting_counterpart", None),
        "receive_note_waiting_for_invoice": ("waiting_counterpart", None),
        "automatic_consistent": ("awaiting_confirmation", "consistent"),
        "automatic_quantity_difference": ("needs_attention", "difference"),
    }
    results = []
    for scenario, keys, primary_key in scenarios:
        details = {
            key: runtime.service.get_document(intakes[key].document.document_id)
            for key in keys
        }
        primary = details[primary_key]
        outcome = primary.preview.result.outcome.value if primary.preview else None
        actual = (primary.document.display_status.value, outcome)
        if actual != expected[scenario]:
            raise RuntimeError(
                f"Demo scenario {scenario} produced {actual}, expected {expected[scenario]}."
            )
        results.append(
            DemoScenarioResult(
                scenario=scenario,
                document_ids={key: detail.document.document_id for key, detail in details.items()},
                display_status=actual[0],
                preview_outcome=outcome,
            )
        )
    return results


def format_results(results: list[DemoScenarioResult]) -> str:
    """Return the only user-facing output: IDs and visible business states."""

    return "\n".join(
        json.dumps(
            {
                "scenario": result.scenario,
                "document_ids": result.document_ids,
                "display_status": result.display_status,
                "preview_outcome": result.preview_outcome,
            },
            sort_keys=True,
        )
        for result in results
    )


def _build_runtime(settings: Settings) -> DemoRuntime:
    ensure_development_environment(settings.app_env)
    if not settings.workspace_enabled:
        raise SystemExit("Set WORKSPACE_ENABLED=true before creating demo data.")
    if not settings.workspace_tenant_id or not settings.workspace_store_id:
        raise SystemExit("Configure WORKSPACE_TENANT_ID and WORKSPACE_STORE_ID first.")

    session_factory = get_session_factory()
    with session_factory() as session:
        admin = session.scalar(
            select(AdminUserRow).where(
                AdminUserRow.username == DEMO_ADMIN_USERNAME,
                AdminUserRow.is_active.is_(True),
            )
        )
    if admin is None:
        raise SystemExit("adminuser is missing; run setup_dev_admin.py first.")

    actor = AuthenticatedUser(
        user_id=admin.user_id,
        username=admin.username,
        role=AdminRole(admin.role),
    )
    storage = MinioObjectStorage(
        endpoint=settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        bucket_name=settings.minio_bucket_name,
        secure=settings.minio_secure,
    )
    repository = PostgresWorkspaceRepository(session_factory)
    service = WorkspaceService(
        repository=repository,
        upload_service=DocumentUploadService(
            storage=storage,
            repository=PostgresExtractionTaskRepository(session_factory),
            max_bytes=settings.upload_max_bytes,
        ),
        storage=storage,
        scope=WorkspaceScopeKey(
            tenant_id=settings.workspace_tenant_id,
            store_id=settings.workspace_store_id,
        ),
    )
    return DemoRuntime(
        session_factory=session_factory,
        service=service,
        repository=repository,
        worker=WorkspaceWorker(
            repository,
            WorkspaceScopeKey(
                tenant_id=settings.workspace_tenant_id,
                store_id=settings.workspace_store_id,
            ),
        ),
        actor=actor,
    )


def main() -> None:
    settings = get_settings()
    ensure_development_environment(settings.app_env)
    results = setup_demo_data(_build_runtime(settings))
    print(format_results(results))


if __name__ == "__main__":
    main()
