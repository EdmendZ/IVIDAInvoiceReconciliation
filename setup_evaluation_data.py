"""Import the local Gold evaluation set into the development workspace."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.domain.documents import DocumentType, Invoice, ReceiveNote
from app.domain.workspace import UploadCommand
from app.infra.database_models import (
    DocumentDraftRow,
    ExtractionRunRow,
    ExtractionTaskRow,
)
from setup_demo_data import DemoRuntime, _build_runtime, ensure_development_environment


EVALUATION_FIXTURE_MARKER = "ir-simple-evaluation-v1"
DATASET_ROOT = Path(__file__).resolve().parent / "evaluation_data"
MANIFEST_PATH = DATASET_ROOT / "manifest.json"


@dataclass(frozen=True)
class EvaluationDocument:
    case_id: str
    key: str
    relative_path: str
    filename: str
    document_type: DocumentType
    payload: dict[str, Any]
    data: bytes


@dataclass(frozen=True)
class EvaluationCaseResult:
    case_id: str
    invoice_document_id: str
    receive_note_document_ids: list[str]
    display_status: str
    match_status: str
    preview_outcome: str | None


def _dataset_path(relative_path: str) -> Path:
    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise SystemExit(f"Evaluation dataset path is outside the dataset: {relative_path}")
    path = (DATASET_ROOT / relative).resolve()
    if not path.is_relative_to(DATASET_ROOT.resolve()):
        raise SystemExit(f"Evaluation dataset path is outside the dataset: {relative_path}")
    return path


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Cannot read evaluation dataset file: {path}") from exc
    if not isinstance(value, dict):
        raise SystemExit(f"Evaluation dataset file must contain an object: {path}")
    return value


def _validate_payload(payload: dict[str, Any], document_type: DocumentType) -> None:
    model = Invoice if document_type is DocumentType.INVOICE else ReceiveNote
    try:
        model.model_validate(payload)
    except ValueError as exc:
        raise SystemExit(
            f"Gold payload is invalid for {document_type.value}: {payload.get('document_number')}"
        ) from exc


def load_evaluation_documents() -> tuple[dict[str, Any], list[EvaluationDocument]]:
    """Load and cross-check manifest, source PDFs and Gold payloads."""

    if not MANIFEST_PATH.is_file():
        raise SystemExit(
            f"Evaluation dataset is missing: {MANIFEST_PATH}. "
            "Generate or restore evaluation_data before importing it."
        )
    manifest = _read_json(MANIFEST_PATH)
    if manifest.get("synthetic") is not True:
        raise SystemExit("Refusing to import a dataset that is not marked synthetic.")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or manifest.get("case_count") != len(cases):
        raise SystemExit("Evaluation manifest case_count does not match its cases.")

    documents: list[EvaluationDocument] = []
    seen_paths: set[str] = set()
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("case_id"), str):
            raise SystemExit("Evaluation manifest contains an invalid case.")
        case_id = case["case_id"]
        request = _read_json(_dataset_path(case["gold_request"]))
        invoice = request.get("invoice")
        receive_notes = request.get("receive_notes")
        if not isinstance(invoice, dict) or not isinstance(receive_notes, list):
            raise SystemExit(f"Gold request is incomplete: {case_id}")
        by_number = {invoice.get("document_number"): invoice}
        by_number.update(
            {
                note.get("document_number"): note
                for note in receive_notes
                if isinstance(note, dict)
            }
        )
        for relative_path in case.get("documents", []):
            if not isinstance(relative_path, str) or relative_path in seen_paths:
                raise SystemExit(f"Duplicate or invalid evaluation document path: {relative_path}")
            seen_paths.add(relative_path)
            source_path = _dataset_path(relative_path)
            if not source_path.is_file():
                raise SystemExit(f"Evaluation source document is missing: {source_path}")
            filename = source_path.name
            stem_parts = source_path.stem.split("__", 1)
            if len(stem_parts) != 2 or stem_parts[0] not in {"invoice", "receive_note"}:
                raise SystemExit(f"Evaluation source filename is invalid: {filename}")
            document_type = (
                DocumentType.INVOICE
                if stem_parts[0] == "invoice"
                else DocumentType.RECEIVE_NOTE
            )
            document_number = stem_parts[1]
            payload = by_number.get(document_number)
            if payload is None or payload.get("document_type") != document_type.value:
                raise SystemExit(
                    f"Source and Gold document do not agree: {case_id}/{filename}"
                )
            _validate_payload(payload, document_type)
            data = source_path.read_bytes()
            if not data.startswith(b"%PDF"):
                raise SystemExit(f"Evaluation source is not a PDF: {source_path}")
            documents.append(
                EvaluationDocument(
                    case_id=case_id,
                    key=f"{case_id}:{document_type.value}:{document_number}",
                    relative_path=relative_path,
                    filename=filename,
                    document_type=document_type,
                    payload=payload,
                    data=data,
                )
            )
    if len(documents) != 17:
        raise SystemExit(f"Expected 17 evaluation documents, found {len(documents)}")
    return manifest, documents


def _fixture_owned(run: ExtractionRunRow) -> bool:
    return bool(
        isinstance(run.raw_output, dict)
        and run.raw_output.get("fixture_kind") == EVALUATION_FIXTURE_MARKER
    )


def _persist_evaluation_draft(
    session_factory: sessionmaker[Session],
    document: EvaluationDocument,
    *,
    task_id: str,
    run_id: str,
    duplicate: bool,
    source_sha256: str,
) -> None:
    """Write one Gold Draft, refusing to overwrite non-evaluation work."""

    with session_factory.begin() as session:
        task = session.get(ExtractionTaskRow, task_id)
        run = session.get(ExtractionRunRow, run_id)
        if task is None or run is None or run.task_id != task_id:
            raise RuntimeError("Upload did not create the expected Task and Run.")
        if task.sha256 != source_sha256 or task.original_filename != document.filename:
            raise RuntimeError("Refusing to modify an upload that is not this evaluation source.")

        draft = session.scalar(
            select(DocumentDraftRow).where(DocumentDraftRow.run_id == run_id)
        )
        if draft is not None:
            if not _fixture_owned(run) or draft.normalized_json != document.payload:
                raise RuntimeError("Refusing to modify an existing non-evaluation Draft.")
            return
        if duplicate or _fixture_owned(run) or run.status != "queued":
            raise RuntimeError("Refusing to replace an existing non-evaluation Run.")

        now = datetime.now(UTC)
        task.status = "ready_for_review"
        task.error_message = None
        task.updated_at = now
        run.provider = "evaluation_fixture"
        run.model_name = EVALUATION_FIXTURE_MARKER
        run.status = "ready_for_review"
        run.raw_output = {
            "fixture_kind": EVALUATION_FIXTURE_MARKER,
            "case_id": document.case_id,
            "source_path": document.relative_path,
            "notice": "Local Gold fixture; OCR and model extraction were bypassed.",
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
                draft_id=str(
                    uuid5(NAMESPACE_URL, f"{EVALUATION_FIXTURE_MARKER}:draft:{task_id}")
                ),
                run_id=run_id,
                task_id=task_id,
                document_type=document.document_type.value,
                normalized_json=document.payload,
                validation_state="valid",
                created_at=now,
                updated_at=now,
            )
        )


def setup_evaluation_data(runtime: DemoRuntime) -> list[EvaluationCaseResult]:
    """Import all 17 documents and compute their current workspace previews."""

    _manifest, documents = load_evaluation_documents()
    intakes = {}
    for document in documents:
        intake = runtime.service.upload(
            UploadCommand(
                document_type=document.document_type,
                filename=document.filename,
                data=document.data,
            ),
            runtime.actor,
            str(uuid5(NAMESPACE_URL, f"{EVALUATION_FIXTURE_MARKER}:upload:{document.key}")),
        )
        _persist_evaluation_draft(
            runtime.session_factory,
            document,
            task_id=intake.task_id,
            run_id=intake.run_id,
            duplicate=intake.duplicate,
            source_sha256=hashlib.sha256(document.data).hexdigest(),
        )
        intakes[document.key] = intake

    tick = runtime.worker.tick()
    if tick.errors:
        raise RuntimeError(f"Workspace Worker reported {tick.errors} evaluation error(s).")

    results = []
    case_ids = list(dict.fromkeys(document.case_id for document in documents))
    for case_id in case_ids:
        invoice = next(
            document
            for document in documents
            if document.case_id == case_id and document.document_type is DocumentType.INVOICE
        )
        receive_notes = [
            document
            for document in documents
            if document.case_id == case_id and document.document_type is DocumentType.RECEIVE_NOTE
        ]
        detail = runtime.service.get_document(intakes[invoice.key].document.document_id)
        if detail.current_revision is None:
            raise RuntimeError(f"Evaluation invoice did not become ready: {case_id}")
        preview_outcome = detail.preview.result.outcome.value if detail.preview else None
        results.append(
            EvaluationCaseResult(
                case_id=case_id,
                invoice_document_id=detail.document.document_id,
                receive_note_document_ids=[
                    intakes[document.key].document.document_id for document in receive_notes
                ],
                display_status=detail.document.display_status.value,
                match_status=detail.match_status.value,
                preview_outcome=preview_outcome,
            )
        )
    return results


def format_results(results: list[EvaluationCaseResult]) -> str:
    return "\n".join(
        json.dumps(
            {
                "case_id": result.case_id,
                "invoice_document_id": result.invoice_document_id,
                "receive_note_document_ids": result.receive_note_document_ids,
                "display_status": result.display_status,
                "match_status": result.match_status,
                "preview_outcome": result.preview_outcome,
            },
            sort_keys=True,
        )
        for result in results
    )


def main() -> None:
    settings: Settings = get_settings()
    ensure_development_environment(settings.app_env)
    if not DATASET_ROOT.is_dir():
        raise SystemExit(f"Evaluation dataset is missing: {DATASET_ROOT}")
    results = setup_evaluation_data(_build_runtime(settings))
    print(format_results(results))


if __name__ == "__main__":
    main()
