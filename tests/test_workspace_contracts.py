"""Workspace contracts preserve business values and reject malformed wire input."""
import inspect
import json
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from pydantic import TypeAdapter, ValidationError

from app.domain import workspace as w
from app.domain.documents import Invoice, ReceiveNote
from app.services.workspace_ports import WorkspaceRepository

ID = "00000000-0000-0000-0000-000000000001"
OTHER = "00000000-0000-0000-0000-000000000002"
NOW = datetime(2026, 9, 16, tzinfo=timezone.utc)


def payload(kind="invoice"):
    return {"document_type": kind, "document_number": "INV-English-01",
            "supplier": {"name": "Farmer's Choice Pty Ltd"},
            "items": [{"description": "Free Range Eggs", "quantity": "1.0000000000000000001",
                       "unit": "carton", "unit_price": "12345678901234567890.123456789"}]}


def revision(**changes):
    data = dict(revision_id=ID, document_id=OTHER, sequence=1, origin="extracted",
                payload=payload(), created_at=NOW)
    data.update(changes)
    return data


def confirm(**changes):
    data = dict(expected_revision=1, preview_id=ID, acknowledged_sources=True,
                acknowledged_unverified_dimensions=["tax", "document_total"], resolution="matched")
    data.update(changes)
    return data


def test_precision_english_evidence_and_note_survive_json():
    view = w.RevisionView(**revision(evidence=[dict(field_path="items[0].description",
                         source_text="Free Range Eggs", value="Free Range Eggs")]))
    wire = json.loads(view.model_dump_json())
    assert wire["payload"]["items"][0]["quantity"] == "1.0000000000000000001"
    assert wire["payload"]["items"][0]["unit_price"] == "12345678901234567890.123456789"
    assert wire["payload"]["supplier"]["name"] == "Farmer's Choice Pty Ltd"
    assert wire["evidence"][0]["source_text"] == "Free Range Eggs"
    assert w.RevisionView.model_validate_json(view.model_dump_json()) == view
    note = w.InvestigateCommand(expected_revision=1, note="  Ask supplier about Eggs  ")
    assert note.model_dump(mode="json")["note"] == "Ask supplier about Eggs"


@pytest.mark.parametrize("kind,cls", [("invoice", Invoice), ("receive_note", ReceiveNote)])
def test_payload_union_discriminates(kind, cls):
    assert isinstance(w.RevisionView(**revision(payload=payload(kind))).payload, cls)
    assert isinstance(w.EditCommand(expected_revision=1, reason="Correct SKU", document=payload(kind)).document, cls)


def test_payload_requires_known_discriminator():
    for kind in [None, "purchase_order"]:
        with pytest.raises(ValidationError):
            w.RevisionView(**revision(payload=payload(kind)))


@pytest.mark.parametrize("value", [0.1, float("inf"), "NaN"])
def test_financial_float_and_nonfinite_rejected(value):
    with pytest.raises(ValidationError):
        w.MetricComparison(invoice_value=value, status="unverified")


def test_metric_decimal_serializes_to_string_and_unknown_stays_null():
    metric = w.MetricComparison(invoice_value=Decimal("123456789.00000000000000001"), status="unverified")
    assert metric.model_dump(mode="json") == dict(invoice_value="123456789.00000000000000001",
        received_value=None, difference=None, status="unverified", reason_code=None)


@pytest.mark.parametrize("changes", [dict(expected_revision=0), dict(expected_revision=True),
    dict(preview_id="not-uuid"), dict(acknowledged_sources=False), dict(acknowledged_sources=1),
    dict(acknowledged_unverified_dimensions=["tax", "tax"]),
    dict(resolution="resolved_with_note"), dict(note="   "), dict(note="x" * 2001), dict(unexpected=1)])
def test_confirm_rejects_invalid_input(changes):
    with pytest.raises(ValidationError):
        w.ConfirmCommand(**confirm(**changes))


def test_note_resolution_and_acknowledgement_order():
    command = w.ConfirmCommand(**confirm(resolution="resolved_with_note", note=" Supplier confirmed shortage "))
    assert command.note == "Supplier confirmed shortage"
    assert command.acknowledged_unverified_dimensions == ["tax", "document_total"]


@pytest.mark.parametrize("ids", [[ID, ID], ["bad"], [str(__import__('uuid').UUID(int=i)) for i in range(101)]])
def test_selection_invalid_ids(ids):
    with pytest.raises(ValidationError):
        w.SelectionCommand(expected_revision=1, reason="Use selected deliveries", receive_document_ids=ids)


def test_selection_empty_restores_auto_and_manual_input_cannot_be_empty():
    assert w.SelectionCommand(expected_revision=1, reason="Restore automatic", receive_document_ids=[]).receive_document_ids == []
    with pytest.raises(ValidationError):
        w.PreviewInput(invoice=revision(), receivings=[], used_ids=set(), scope_generation=0,
                       document_revision=1, manual_selection_ids=[])


@pytest.mark.parametrize("data", [dict(page=0), dict(page_size=101), dict(q="x" * 101),
                                     dict(type="purchase_order"), dict(status=["approved"]), dict(tenant_id="outside")])
def test_query_constraints(data):
    with pytest.raises(ValidationError):
        w.DocumentQuery(**data)


def test_query_defaults_do_not_share_mutable_lists():
    first, second = w.DocumentQuery(), w.DocumentQuery()
    first.status.append(w.DisplayStatus.COMPLETED)
    assert second.model_dump(mode="json") == dict(page=1, page_size=20, type="invoice", status=[], q=None)


def test_document_detail_relation_projections_are_explicit_and_round_trip():
    summary = w.DocumentSummary(
        document_id=ID,
        document_type="receive_note",
        source_kind="upload",
        revision=1,
        processing_status="ready",
        display_status="waiting_counterpart",
        document_number="RN-English-01",
        updated_at=NOW,
    )
    detail = w.DocumentDetail(
        document=summary,
        match_status="waiting_counterpart",
        preview_stale=False,
        selected_receiving_source_ids=[OTHER],
        related_invoices=[summary.model_copy(update={"document_id": OTHER, "document_type": w.DocumentType.INVOICE})],
        source_url_available=True,
    )
    assert w.DocumentDetail.model_validate_json(detail.model_dump_json()) == detail
    assert detail.selected_receiving_source_ids == [OTHER]
    assert detail.related_invoices[0].document_id == OTHER


def test_all_new_dtos_forbid_extra_and_protocol_is_complete():
    dtos = [v for v in vars(w).values() if inspect.isclass(v) and issubclass(v, w.WorkspaceDTO)]
    assert len(dtos) >= 35
    assert all(cls.model_config["extra"] == "forbid" for cls in dtos)
    assert {name for name, method in vars(WorkspaceRepository).items() if not name.startswith("_") and callable(method)} == {
        "cached_request", "intake", "list_documents", "get_document", "get_actions", "mutate",
        "get_confirmation", "source_metadata", "sync_sources", "pending_previews", "save_preview", "runtime"}
    assert inspect.signature(WorkspaceRepository.pending_previews).parameters["limit"].default == 100


def test_command_union_does_not_swallow_invalid_extra_fields():
    adapter = TypeAdapter(w.WorkspaceCommand)
    assert isinstance(adapter.validate_python(confirm()), w.ConfirmCommand)
    assert isinstance(adapter.validate_python(dict(expected_revision=1, reason="Reopen")), w.ReasonCommand)
    with pytest.raises(ValidationError):
        adapter.validate_python(confirm(injected_sql="DROP TABLE"))


def test_status_dimensions_remain_separate():
    assert set(w.ProcessingStatus) == {"processing", "ready", "failed", "cancelled", "voided"}
    assert set(w.ReviewStatus) == {"open", "investigating", "completed"}
    assert set(w.MatchStatus) == {"waiting_counterpart", "needs_selection", "selected"}
    assert set(w.WorkspaceOperation) == {"edit", "select", "investigate", "confirm", "reopen", "void", "retry"}
    assert "approved" not in set(w.DisplayStatus)


def test_utc_and_scope_encoding():
    assert w.RevisionView(**revision(created_at="2026-09-16T08:00:00+08:00")).created_at.hour == 0
    with pytest.raises(ValidationError):
        w.RevisionView(**revision(created_at=datetime(2026, 9, 16)))
    one = w.WorkspaceScopeKey(tenant_id="a/b", store_id="c")
    two = w.WorkspaceScopeKey(tenant_id="a", store_id="b/c")
    assert one.scope_id != two.scope_id
    assert json.loads(one.scope_id) == ["a/b", "c"]


def test_workspace_record_source_constraints_and_no_derived_columns():
    data = dict(document_id=ID, tenant_id="tenant", store_id="store", document_type="invoice",
                source_kind="upload", task_id=OTHER, review_status="open", created_at=NOW, updated_at=NOW)
    assert w.WorkspaceDocument(**data).revision == 1
    for changes in [dict(task_id=None), dict(review_status=None), dict(display_status="processing"),
                    dict(processing_status="ready"), dict(selected_document_ids=[OTHER, ID]),
                    dict(selection_origin="manual")]:
        with pytest.raises(ValidationError):
            w.WorkspaceDocument(**(data | changes))
    with pytest.raises(ValidationError):
        w.WorkspaceRevision(**revision(), content_sha256="abc")
    assert w.WorkspaceRevision(**revision(), content_sha256="abc", source_draft_id=OTHER).source_draft_id == OTHER
    with pytest.raises(ValidationError):
        w.WorkspaceRevision(**revision(), content_sha256="abc", source_draft_id=OTHER, source_version_id=ID)


def test_preview_keeps_tax_total_unverified_and_fixed_tolerances():
    data = dict(outcome="consistent", coverage="quantity_only", summary=dict(total_lines=0, different_lines=0, unverified_lines=0),
                subject=dict(supplier="equal", currency="equal"))
    assert w.PreviewResult(**data).unverified_dimensions == ["document_total", "tax"]
    with pytest.raises(ValidationError):
        w.PreviewResult(**data, unverified_dimensions=[])
    with pytest.raises(ValidationError):
        w.PreviewResult(**data, blocking_codes=["PO_MATCH"])
    with pytest.raises(ValidationError):
        w.Tolerances(amount="1.00")
    assert w.Tolerances().model_dump(mode="json") == dict(quantity="0", unit_price="0.01", amount="0.02")


def test_confirmation_history_numbers_are_required_and_roundtrip():
    data = dict(confirmation_id=ID, preview_id=OTHER, invoice_number="INV-original",
                receive_note_numbers=["RN-02", "RN-01"], resolution="matched",
                acknowledged_unverified_dimensions=["tax", "document_total"],
                result_snapshot=dict(outcome="consistent", coverage="quantity_only",
                    summary=dict(total_lines=0, different_lines=0, unverified_lines=0),
                    subject=dict(supplier="equal", currency="equal")),
                input_revision_ids=[ID, OTHER], actor_id=ID, created_at=NOW)
    view = w.ConfirmationView(**data)
    assert w.ConfirmationView.model_validate_json(view.model_dump_json()) == view
    assert view.receive_note_numbers == ["RN-02", "RN-01"]
    for field in ["invoice_number", "receive_note_numbers"]:
        with pytest.raises(ValidationError):
            w.ConfirmationView(**{key: value for key, value in data.items() if key != field})
