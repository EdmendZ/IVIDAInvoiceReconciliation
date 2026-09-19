"""Real PostgreSQL acceptance; every test database connection uses a private schema."""
import importlib.util
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, event, func, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from app.domain import workspace as w
from app.domain.document_versions import DocumentVersion
from app.domain.extraction_tasks import ExtractionTask
from app.infra.database import Base
from app.infra import database_models as m
from app.infra.postgres_workspace_repository import PostgresWorkspaceRepository
from app.infra.postgres_taptouch_receiving_repository import PostgresTaptouchReceivingRepository
from app.services.workspace_matching import select_candidates
from app.services.workspace_comparison import compare_workspace


def uid():
    return str(uuid4())


def now():
    return datetime.now(UTC)


@pytest.fixture(scope="module")
def database():
    value = os.environ.get("WORKSPACE_TEST_DATABASE_URL")
    if not value:
        pytest.skip("WORKSPACE_TEST_DATABASE_URL must point to a disposable PostgreSQL database")
    url = make_url(value)
    if url.get_backend_name() != "postgresql" or not (url.database or "").endswith("_workspace_test"):
        pytest.fail("Refusing non-disposable workspace test database")
    schema = "ws_test_" + uuid4().hex
    assert re.fullmatch(r"ws_test_[a-f0-9]{32}", schema)
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    try:
        Base.metadata.create_all(engine, tables=[t for t in Base.metadata.sorted_tables if not t.name.startswith("ws_")])
        spec = importlib.util.spec_from_file_location("workspace_migration", Path("migrations/versions/20260916_15_workspace.py"))
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        with engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        yield engine, migration
    finally:
        engine.dispose()
        assert re.fullmatch(r"ws_test_[a-f0-9]{32}", schema)
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


@pytest.fixture
def ctx(database):
    engine, _ = database
    factory = sessionmaker(engine, autoflush=False, expire_on_commit=False)
    actor = uid()
    with factory.begin() as session:
        session.add(m.AdminUserRow(user_id=actor, username=actor, password_hash="not-a-credential",
                                  role="reviewer", is_active=True, created_at=now()))
    scope = w.WorkspaceScopeKey(tenant_id=uid(), store_id="store")
    return PostgresWorkspaceRepository(factory), factory, scope, actor


def payload(kind="invoice", number="INV-1", **overrides):
    data = dict(document_type=kind, document_number=number, currency="AUD", document_date="2026-09-16",
                purchase_order_number="PO-1", supplier={"name": "Fresh Foods"},
                items=[dict(sku="EGGS", description="Free Range Eggs", quantity="10", unit="bag")])
    data.update(overrides)
    return data


def intake(ctx, kind="invoice", digest=None):
    repo, _, scope, actor = ctx
    task = ExtractionTask(task_id=uid(), document_type=kind, original_filename="English.pdf",
        content_type="application/pdf", size_bytes=5, sha256=digest or uid(), storage_bucket="test",
        storage_object_key=uid(), status="uploaded", created_at=now(), updated_at=now())
    return repo.intake(scope, w.PreparedUpload(task=task), actor, uid(), uid())


def ready(ctx, kind="invoice", number="INV-1", **overrides):
    repo, factory, scope, _ = ctx
    response = intake(ctx, kind)
    with factory.begin() as session:
        run = session.get(m.ExtractionRunRow, response.run_id)
        run.status = "ready_for_review"
        session.add(m.DocumentDraftRow(draft_id=uid(), run_id=run.run_id, task_id=response.task_id,
            document_type=kind, normalized_json=payload(kind, number, **overrides), validation_state="valid",
            created_at=now(), updated_at=now()))
    repo.sync_sources(scope)
    return response.document.document_id


def upstream(ctx, identity="RN", number="RN-1", version=1, status="active", **overrides):
    _, factory, scope, _ = ctx
    value = DocumentVersion(version_id=uid(), document_type="receive_note", document_json=payload("receive_note", number, **overrides),
        status="approved", approved_at=now(), created_at=now(), source_kind="taptouch_receiving",
        trust_method="upstream_authoritative", source_system="taptouch", integration_principal="test",
        external_tenant_id=scope.tenant_id, external_store_id=scope.store_id,
        external_supplier_id="supplier", external_receiving_id=identity, external_version=version,
        record_status=status, upstream_updated_at=now())
    return PostgresTaptouchReceivingRepository(factory).import_version(value).version


def previews(ctx):
    repo, _, scope, _ = ctx
    for input in repo.pending_previews(scope):
        proposal = select_candidates(input.invoice, input.receivings, input.used_ids)
        if input.manual_selection_ids:
            proposal.selected_document_ids = input.manual_selection_ids
            proposal.status = "selected"
        receives = [r for r in input.receivings if r.document_id in proposal.selected_document_ids]
        result = compare_workspace(input.invoice, receives) if proposal.selected_document_ids else None
        assert repo.save_preview(scope, input, proposal, result)


def confirm(ctx, doc_id, key=None, request_hash=None):
    repo, _, scope, actor = ctx
    detail = repo.get_document(scope, doc_id)
    command = w.ConfirmCommand(expected_revision=detail.document.revision, preview_id=detail.preview.preview_id,
        acknowledged_sources=True, acknowledged_unverified_dimensions=detail.preview.result.unverified_dimensions,
        resolution="resolved_with_note" if detail.preview.result.outcome == "difference" else "matched",
        note="Supplier contacted" if detail.preview.result.outcome == "difference" else None)
    return repo.mutate(scope, doc_id, "confirm", command, actor, key or uid(), request_hash or uid())


def mutation(ctx, doc_id, operation, cls=w.ReasonCommand, **kwargs):
    repo, _, scope, actor = ctx
    command = cls(expected_revision=repo.get_document(scope, doc_id).document.revision, **kwargs)
    return repo.mutate(scope, doc_id, operation, command, actor, uid(), uid())


def count(factory, cls):
    with factory() as session:
        return session.scalar(select(func.count()).select_from(cls))


def test_migration_matches_metadata_and_jsonb(database):
    engine, _ = database
    with engine.connect() as connection:
        diffs = compare_metadata(MigrationContext.configure(connection, opts={"compare_type": True}), Base.metadata)
        assert diffs == []
        assert len([t for t in inspect(connection).get_table_names() if t.startswith("ws_")]) == 8
        for table in ("ws_revisions", "ws_previews", "ws_confirmations"):
            assert any(str(c["type"]) == "JSONB" for c in inspect(connection).get_columns(table))


def test_intake_duplicate_idempotency_conflict_and_scope(ctx):
    repo, factory, scope, actor = ctx
    first = intake(ctx, digest="same")
    other = intake(ctx, digest="same")
    assert other.duplicate and not first.duplicate
    assert (other.document.document_id, other.task_id, other.run_id) == (first.document.document_id, first.task_id, first.run_id)
    with factory() as session:
        run = session.get(m.ExtractionRunRow, first.run_id)
        assert run.status == "queued" and run.provider == run.model_name == "disabled"
        assert session.get(m.ExtractionTaskRow, first.task_id).status == "extracting"
    key = uid()
    command = w.ReasonCommand(expected_revision=first.document.revision, reason="Duplicate file")
    response = repo.mutate(scope, first.document.document_id, "void", command, actor, key, "hash")
    assert repo.mutate(scope, first.document.document_id, "void", command, actor, key, "hash") == response
    with pytest.raises(w.WorkspaceError, match="请求标识"):
        repo.mutate(scope, first.document.document_id, "void", command, actor, key, "different")
    assert intake(ctx, digest="same").document.document_id != first.document.document_id
    with pytest.raises(w.WorkspaceError) as exc:
        repo.get_document(w.WorkspaceScopeKey(tenant_id="other", store_id="store"), first.document.document_id)
    assert exc.value.detail.code == "DOCUMENT_NOT_FOUND"


def test_preview_cas_no_fake_result_and_readonly_get(ctx):
    repo, factory, scope, _ = ctx
    doc_id = ready(ctx)
    before = count(factory, m.WorkspacePreviewRow)
    input = repo.pending_previews(scope)[0]
    proposal = select_candidates(input.invoice, input.receivings, input.used_ids)
    assert repo.save_preview(scope, input, proposal, None)
    detail = repo.get_document(scope, doc_id)
    assert detail.preview is None and not detail.preview_stale
    assert detail.document.display_status == "waiting_counterpart"
    assert detail.document.revision == input.document_revision + 1
    assert not repo.save_preview(scope, input, proposal, None)
    assert count(factory, m.WorkspacePreviewRow) == before
    empty = w.WorkspaceScopeKey(tenant_id=uid(), store_id="store")
    repo.list_documents(empty, w.DocumentQuery())
    repo.runtime(empty)
    with factory() as session:
        assert session.get(m.WorkspaceScopeRow, empty.scope_id) is None
    ready(ctx, "receive_note", "RN")
    stale = repo.pending_previews(scope)[0]
    ready(ctx, "receive_note", "RN-2")
    assert not repo.save_preview(scope, stale, proposal, None)


def test_detail_projects_selected_sources_and_reverse_invoice_relation(ctx):
    repo, _, scope, _ = ctx
    invoice = ready(ctx, "invoice", "INV-RELATION")
    receiving = ready(ctx, "receive_note", "RN-RELATION")
    previews(ctx)

    invoice_detail = repo.get_document(scope, invoice)
    assert invoice_detail.document.selected_document_ids == [receiving]
    assert invoice_detail.selected_receiving_source_ids == [receiving]
    assert invoice_detail.related_invoices == []

    receive_detail = repo.get_document(scope, receiving)
    assert [item.document_id for item in receive_detail.related_invoices] == [invoice]
    assert receive_detail.related_invoices[0].document_number == "INV-RELATION"


def test_confirm_replay_reopen_history_and_source_change(ctx):
    repo, factory, scope, actor = ctx
    invoice = ready(ctx)
    upstream(ctx)
    assert repo.sync_sources(scope).changed_documents == 1
    previews(ctx)
    detail = repo.get_document(scope, invoice)
    key = uid()
    command = w.ConfirmCommand(expected_revision=detail.document.revision, preview_id=detail.preview.preview_id,
        acknowledged_sources=True, acknowledged_unverified_dimensions=detail.preview.result.unverified_dimensions, resolution="matched")
    first = repo.mutate(scope, invoice, "confirm", command, actor, key, "same")
    assert first.document.display_status == "completed"
    assert first.confirmation.invoice_number == "INV-1"
    assert first.confirmation.receive_note_numbers == ["RN-1"]
    assert repo.mutate(scope, invoice, "confirm", command, actor, key, "same") == first
    with factory() as session:
        assert len(list(session.scalars(select(m.WorkspaceClaimRow).where(m.WorkspaceClaimRow.invoice_document_id == invoice)))) == 1
    upstream(ctx, version=2, number="RN-new")
    repo.sync_sources(scope)
    assert repo.get_document(scope, invoice).document.source_changed
    assert repo.get_confirmation(scope, first.confirmation.confirmation_id) == first.confirmation
    reopened = mutation(ctx, invoice, "reopen", reason="Source corrected")
    assert reopened.revision == repo.get_actions(scope, invoice, 1, 20).items[0].new_revision
    assert repo.get_document(scope, invoice).confirmation is None
    previews(ctx)
    second = confirm(ctx, invoice)
    assert second.confirmation.confirmation_id != first.confirmation.confirmation_id
    assert second.confirmation.receive_note_numbers == ["RN-new"]
    assert repo.get_confirmation(scope, first.confirmation.confirmation_id).receive_note_numbers == ["RN-1"]
    history = repo.list_confirmations(scope, w.ConfirmationQuery(page_size=1))
    repeated = repo.list_confirmations(scope, w.ConfirmationQuery(page_size=1))
    assert history.total == 2
    assert [item.confirmation_id for item in history.items] == [item.confirmation_id for item in repeated.items]
    old = repo.list_confirmations(scope, w.ConfirmationQuery(q="rn-1"))
    assert [item.confirmation_id for item in old.items] == [first.confirmation.confirmation_id]
    assert old.items[0].invoice_number == "INV-1"
    assert old.items[0].supplier_name == "Fresh Foods"
    assert old.items[0].receive_note_numbers == ["RN-1"]
    assert repo.list_confirmations(scope, w.ConfirmationQuery(q="fresh foods")).total == 2
    assert repo.list_confirmations(scope, w.ConfirmationQuery(outcome=["difference"])).total == 0
    assert repo.list_confirmations(
        w.WorkspaceScopeKey(tenant_id=uid(), store_id="store"), w.ConfirmationQuery()
    ).total == 0


@pytest.mark.parametrize("status", ["active", "voided"])
def test_unsynced_upstream_version_rejects_confirmation(ctx, status):
    repo, _, scope, _ = ctx
    invoice = ready(ctx)
    upstream(ctx)
    repo.sync_sources(scope)
    previews(ctx)
    upstream(ctx, version=2, status=status)
    with pytest.raises(w.WorkspaceError) as exc:
        confirm(ctx, invoice)
    assert exc.value.detail.code == "PREVIEW_STALE"
    assert repo.get_document(scope, invoice).preview_stale


def test_atomic_rollback_injected_action_failure(ctx, database):
    repo, factory, scope, _ = ctx
    invoice = ready(ctx)
    ready(ctx, "receive_note", "RN")
    previews(ctx)
    detail = repo.get_document(scope, invoice)
    before = {cls: count(factory, cls) for cls in [m.WorkspaceConfirmationRow, m.WorkspaceClaimRow, m.WorkspaceRequestRow]}
    def fail(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO ws_actions"):
            raise RuntimeError("injected action write failure")
    event.listen(database[0], "before_cursor_execute", fail)
    try:
        with pytest.raises(RuntimeError, match="injected"):
            confirm(ctx, invoice)
    finally:
        event.remove(database[0], "before_cursor_execute", fail)
    assert repo.get_document(scope, invoice) == detail
    assert {cls: count(factory, cls) for cls in before} == before


def test_two_invoices_concurrently_claim_one_receiving(ctx):
    repo, factory, scope, actor = ctx
    one, two = ready(ctx, number="I-1"), ready(ctx, number="I-2")
    ready(ctx, "receive_note", "RN")
    previews(ctx)
    commands = {}
    for doc in [one, two]:
        detail = repo.get_document(scope, doc)
        commands[doc] = w.ConfirmCommand(expected_revision=detail.document.revision, preview_id=detail.preview.preview_id,
            acknowledged_sources=True, acknowledged_unverified_dimensions=detail.preview.result.unverified_dimensions, resolution="matched")
    barrier = Barrier(2)
    def worker(doc):
        barrier.wait(timeout=5)
        try:
            return repo.mutate(scope, doc, "confirm", commands[doc], actor, uid(), uid())
        except w.WorkspaceError as exc:
            return exc.detail.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(worker, [one, two]))
    assert sum(isinstance(r, w.ConfirmationResponse) for r in results) == 1
    assert "RECEIVING_IN_USE" in results


def test_manual_selection_bypasses_date_po_not_subject_and_stays_frozen(ctx):
    repo, _, scope, _ = ctx
    invoice = ready(ctx)
    rn = ready(ctx, "receive_note", "RN", document_date=None, purchase_order_number="OTHER")
    mutation(ctx, invoice, "select", w.SelectionCommand, receive_document_ids=[rn], reason="Original delivery checked")
    previews(ctx)
    assert repo.get_document(scope, invoice).document.selected_document_ids == [rn]
    other = ready(ctx, "receive_note", "RN-2")
    previews(ctx)
    assert repo.get_document(scope, invoice).document.selected_document_ids == [rn]
    mutation(ctx, rn, "void", reason="Invalid source")
    previews(ctx)
    detail = repo.get_document(scope, invoice)
    assert detail.selection_origin == "manual" and detail.document.selected_document_ids == [rn]
    assert "SOURCE_VOIDED" in detail.preview.result.blocking_codes
    mutation(ctx, other, "edit", w.EditCommand, document=payload("receive_note", "RN-2", supplier={"name": "Other"}), reason="Correct supplier")
    with pytest.raises(w.WorkspaceError) as exc:
        mutation(ctx, invoice, "select", w.SelectionCommand, receive_document_ids=[other], reason="Try other")
    assert exc.value.detail.code == "SUBJECT_CONFLICT"


def test_duplicate_invoice_blocks_and_does_not_delete(ctx):
    repo, _, scope, _ = ctx
    invoice = ready(ctx)
    duplicate = ready(ctx, number="inv 1")
    ready(ctx, "receive_note", "RN")
    previews(ctx)
    with pytest.raises(w.WorkspaceError) as exc:
        confirm(ctx, invoice)
    assert exc.value.detail.code == "DUPLICATE_INVOICE"
    mutation(ctx, duplicate, "void", reason="Duplicate invoice")
    previews(ctx)
    assert confirm(ctx, invoice).document.display_status == "completed"


def test_manual_edit_evidence_and_retry_guards(ctx):
    repo, factory, scope, _ = ctx
    invoice = ready(ctx)
    prior = repo.get_document(scope, invoice).current_revision
    mutation(ctx, invoice, "edit", w.EditCommand, document=payload(number="Corrected"), reason="Correct original")
    manual = repo.get_document(scope, invoice).current_revision
    assert manual.origin == "manual" and manual.evidence_origin_revision_id == prior.revision_id
    assert manual.evidence == prior.evidence
    assert repo.sync_sources(scope).changed_documents == 0
    pending = intake(ctx)
    with factory.begin() as session:
        session.get(m.ExtractionRunRow, pending.run_id).status = "failed"
    repo.sync_sources(scope)
    response = mutation(ctx, pending.document.document_id, "retry", w.RevisionCommand)
    assert response.run_id != pending.run_id
    with pytest.raises(w.WorkspaceError):
        mutation(ctx, pending.document.document_id, "retry", w.RevisionCommand)


def test_immutable_history_database_triggers(ctx):
    repo, factory, scope, _ = ctx
    invoice = ready(ctx)
    ready(ctx, "receive_note", "RN")
    previews(ctx)
    confirm(ctx, invoice)
    for table in ["ws_revisions", "ws_previews", "ws_confirmations", "ws_actions"]:
        for operation in ["DELETE", "UPDATE"]:
            with pytest.raises(DBAPIError):
                with factory.begin() as session:
                    sql = f"DELETE FROM {table}" if operation == "DELETE" else f"UPDATE {table} SET created_at = created_at"
                    session.execute(text(sql))


def test_runtime_idempotent_sync_and_literal_search(ctx):
    repo, factory, scope, _ = ctx
    invoice = ready(ctx, number="ABC%_English")
    repo.sync_sources(scope)
    runtime = repo.runtime(scope)
    assert runtime.worker_online and runtime.preview_lag_seconds >= 0
    before = count(factory, m.WorkspaceRevisionRow)
    with factory() as session:
        generation = session.get(m.WorkspaceScopeRow, scope.scope_id).generation
    assert repo.sync_sources(scope).scope_generation == generation
    assert count(factory, m.WorkspaceRevisionRow) == before
    assert repo.list_documents(scope, w.DocumentQuery(q="%_")).items[0].document_id == invoice
    assert repo.list_documents(scope, w.DocumentQuery(q="absent%")).total == 0
    with factory.begin() as session:
        session.get(m.WorkspaceScopeRow, scope.scope_id).last_sync_at = now() - timedelta(seconds=16)
    assert not repo.runtime(scope).worker_online
    assert repo.runtime(scope).preview_lag_seconds is None


def test_reject_downgrade_with_data(database, ctx):
    engine, migration = database
    intake(ctx)
    with pytest.raises(RuntimeError, match="populated"):
        with engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()


def test_unsynced_new_ready_upload_invalidates_automatic_confirmation(ctx):
    repo, factory, scope, _ = ctx
    invoice = ready(ctx)
    ready(ctx, "receive_note", "RN")
    pending = intake(ctx, "receive_note")
    previews(ctx)
    with factory.begin() as session:
        session.get(m.ExtractionRunRow, pending.run_id).status = "ready_for_review"
        session.add(m.DocumentDraftRow(draft_id=uid(), task_id=pending.task_id, run_id=pending.run_id,
            document_type="receive_note", normalized_json=payload("receive_note", "LATE"),
            validation_state="valid", created_at=now(), updated_at=now()))
    with pytest.raises(w.WorkspaceError) as exc:
        confirm(ctx, invoice)
    assert exc.value.detail.code == "PREVIEW_STALE"


def test_legacy_receiving_identity_remains_used_after_version_update(ctx):
    repo, factory, scope, actor = ctx
    version = upstream(ctx)
    invoice = ready(ctx)
    with factory.begin() as session:
        doc = session.get(m.WorkspaceDocumentRow, invoice)
        revision = session.get(m.WorkspaceRevisionRow, doc.current_revision_id)
        old_invoice = m.DocumentVersionRow(version_id=uid(), task_id=doc.task_id,
            source_draft_id=revision.source_draft_id, version_number=1, document_type="invoice",
            document_json=revision.payload, status="approved", created_by=actor, approved_by=actor,
            approved_at=now(), created_at=now(), source_kind="invoice_upload", trust_method="human_approved")
        session.add(old_invoice)
        session.flush()
        reconciliation = m.ReconciliationRow(reconciliation_id=uid(), invoice_version_id=old_invoice.version_id,
            result_json={"immutable_old_result": "preserved"}, created_by=actor, created_at=now())
        session.add(reconciliation)
        session.flush()
        session.add(m.ReconciliationReceiveNoteRow(reconciliation_id=reconciliation.reconciliation_id,
                                                  receive_note_version_id=version.version_id))
    upstream(ctx, version=2)
    repo.sync_sources(scope)
    previews(ctx)
    detail = repo.get_document(scope, invoice)
    assert detail.candidates[0].already_used and not detail.candidates[0].eligible
    rn = detail.candidates[0].document_id
    assert repo.get_document(scope, rn).document.display_status == "completed"
    with pytest.raises(w.WorkspaceError) as exc:
        mutation(ctx, invoice, "select", w.SelectionCommand, receive_document_ids=[rn], reason="Already used")
    assert exc.value.detail.code == "RECEIVING_IN_USE"


def test_parallel_same_key_confirmation_has_one_snapshot(ctx):
    repo, factory, scope, actor = ctx
    invoice = ready(ctx)
    ready(ctx, "receive_note", "RN")
    previews(ctx)
    detail = repo.get_document(scope, invoice)
    command = w.ConfirmCommand(expected_revision=detail.document.revision, preview_id=detail.preview.preview_id,
        acknowledged_sources=True, acknowledged_unverified_dimensions=detail.preview.result.unverified_dimensions, resolution="matched")
    key = uid()
    barrier = Barrier(2)
    def worker(_):
        barrier.wait(timeout=5)
        return repo.mutate(scope, invoice, "confirm", command, actor, key, "parallel")
    before = count(factory, m.WorkspaceConfirmationRow)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(worker, range(2)))
    assert results[0] == results[1]
    assert count(factory, m.WorkspaceConfirmationRow) == before + 1


def test_upstream_scope_lock_serializes_against_confirmation(ctx):
    repo, factory, scope, actor = ctx
    invoice = ready(ctx)
    upstream(ctx)
    repo.sync_sources(scope)
    previews(ctx)
    detail = repo.get_document(scope, invoice)
    command = w.ConfirmCommand(expected_revision=detail.document.revision, preview_id=detail.preview.preview_id,
        acknowledged_sources=True, acknowledged_unverified_dimensions=detail.preview.result.unverified_dimensions, resolution="matched")
    barrier = Barrier(2)
    def write():
        barrier.wait(timeout=5)
        return upstream(ctx, version=2, status="voided")
    def complete():
        barrier.wait(timeout=5)
        try:
            return repo.mutate(scope, invoice, "confirm", command, actor, uid(), uid())
        except w.WorkspaceError as exc:
            return exc.detail.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        update = pool.submit(write)
        result = pool.submit(complete).result(timeout=60)
        update.result(timeout=60)
    repo.sync_sources(scope)
    if isinstance(result, w.ConfirmationResponse):
        assert repo.get_document(scope, invoice).document.source_changed
        assert repo.get_confirmation(scope, result.confirmation.confirmation_id) == result.confirmation
    else:
        assert result == "PREVIEW_STALE"


def test_investigation_and_confirmation_validation(ctx):
    repo, factory, scope, actor = ctx
    invoice = ready(ctx)
    ready(ctx, "receive_note", "RN", items=[dict(sku="EGGS", description="Free Range Eggs", quantity="8", unit="bag")])
    previews(ctx)
    with factory() as session:
        generation = session.get(m.WorkspaceScopeRow, scope.scope_id).generation
    mutation(ctx, invoice, "investigate", w.InvestigateCommand, note="Contact supplier")
    detail = repo.get_document(scope, invoice)
    assert detail.review_status == "investigating" and detail.confirmation is None
    with factory() as session:
        assert session.get(m.WorkspaceScopeRow, scope.scope_id).generation == generation
    command = w.ConfirmCommand(expected_revision=detail.document.revision, preview_id=detail.preview.preview_id,
        acknowledged_sources=True, acknowledged_unverified_dimensions=["tax", "document_total"], resolution="matched")
    with pytest.raises(w.WorkspaceError) as exc:
        repo.mutate(scope, invoice, "confirm", command, actor, uid(), uid())
    assert exc.value.detail.code == "UNVERIFIED_NOT_ACKNOWLEDGED"
    command.acknowledged_unverified_dimensions = detail.preview.result.unverified_dimensions
    with pytest.raises(w.WorkspaceError) as exc:
        repo.mutate(scope, invoice, "confirm", command, actor, uid(), uid())
    assert exc.value.detail.code == "RESOLUTION_NOTE_REQUIRED"
    result = confirm(ctx, invoice)
    assert result.confirmation.resolution == "resolved_with_note"
    assert result.confirmation.result_snapshot.outcome == "difference"


def test_intake_rollback_on_action_failure(ctx, database):
    _, factory, _, _ = ctx
    classes = [m.ExtractionTaskRow, m.ExtractionRunRow, m.WorkspaceDocumentRow, m.WorkspaceRequestRow]
    before = {cls: count(factory, cls) for cls in classes}
    def fail(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO ws_actions"):
            raise RuntimeError("intake action failure")
    event.listen(database[0], "before_cursor_execute", fail)
    try:
        with pytest.raises(RuntimeError, match="intake action failure"):
            intake(ctx)
    finally:
        event.remove(database[0], "before_cursor_execute", fail)
    assert {cls: count(factory, cls) for cls in classes} == before
