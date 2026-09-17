"""PostgreSQL workspace transactions; external I/O never runs under the scope lock."""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.domain import workspace as w
from app.domain.extraction_runs import ExtractionRun
from app.domain.normalization import FieldEvidence
from app.domain.validation import ValidationIssue
from app.infra.database_models import (
    DocumentDraftRow, DocumentVersionRow, ExtractionRunRow, ExtractionTaskRow,
    FieldEvidenceRow, ReconciliationReceiveNoteRow, ValidationIssueRow,
    WorkspaceActionRow as Action, WorkspaceClaimRow as Claim,
    WorkspaceConfirmationRow as Confirmation, WorkspaceDocumentRow as Document,
    WorkspacePreviewRow as Preview, WorkspaceRequestRow as Request,
    WorkspaceRevisionRow as Revision, WorkspaceScopeRow as Scope,
)
from app.services.validation_service import ValidationService
from app.services.workspace_comparison import compare_workspace
from app.services.workspace_matching import normalize_identity, select_candidates

logger = logging.getLogger(__name__)
RULE = "ir-simple-rules-1"
TOLERANCES = w.Tolerances().model_dump(mode="json")


def lock_workspace_scope(session: Session, tenant_id: str, store_id: str) -> None:
    """Shared with upstream ingestion, including when the workspace is disabled."""
    if session.get_bind().dialect.name == "postgresql":
        scope_id = w.WorkspaceScopeKey(tenant_id=tenant_id, store_id=store_id).scope_id
        session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:scope_id, 0))"),
                        {"scope_id": scope_id})


def _id():
    return str(uuid4())


def _now():
    return datetime.now(UTC)


def _hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode("utf-8")).hexdigest()


def _fields(row, cls):
    return {name: getattr(row, name) for name in cls.model_fields if hasattr(row, name)}


def _fail(code, document=None):
    raise w.WorkspaceError(w.WorkspaceErrorCode(code), {
        "DOCUMENT_NOT_FOUND": "未找到单据", "REVISION_CONFLICT": "单据已更新，请查看最新内容",
        "PREVIEW_STALE": "来源或核对预览已更新，请重新核对", "RECEIVING_IN_USE": "收货记录已被使用",
        "IDEMPOTENCY_CONFLICT": "请求标识已用于不同操作", "SUBJECT_CONFLICT": "单据主体或币种不一致",
        "INVALID_TRANSITION": "当前状态不允许此操作", "SOURCE_VOIDED": "来源已作废",
        "SOURCE_REVIEW_REQUIRED": "来源变化需要人工核实", "DUPLICATE_INVOICE": "存在相同编号的发票",
        "VALIDATION_BLOCKED": "请先处理阻断问题", "UNRESOLVED_MATCH": "请先选择收货记录",
        "UNVERIFIED_NOT_ACKNOWLEDGED": "请确认全部未核验维度", "RESOLUTION_NOTE_REQUIRED": "请按核对结果填写处理说明",
        "INVALID_REQUEST": "请求格式无效",
    }.get(code, "操作未完成"), document_id=document.document_id if document else None,
        current_revision=document.revision if document else None)


class PostgresWorkspaceRepository:
    def __init__(self, session_factory: sessionmaker[Session]):
        self._session_factory = session_factory

    @staticmethod
    def _documents(session, scope, *, lock=False):
        statement = select(Document).where(Document.tenant_id == scope.tenant_id,
                                           Document.store_id == scope.store_id).order_by(Document.document_id)
        return list(session.scalars(statement.with_for_update() if lock else statement))

    @staticmethod
    def _document(session, scope, document_id):
        document = session.get(Document, document_id)
        if document is None or (document.tenant_id, document.store_id) != (scope.tenant_id, scope.store_id):
            _fail("DOCUMENT_NOT_FOUND")
        return document

    def _begin(self, session, scope):
        lock_workspace_scope(session, scope.tenant_id, scope.store_id)
        row = session.get(Scope, scope.scope_id)
        if row is None:
            row = Scope(scope_id=scope.scope_id, generation=0, updated_at=_now())
            session.add(row)
            session.flush()
        self._documents(session, scope, lock=True)
        return row

    @staticmethod
    def _cached(session, scope, actor_id, key, request_hash):
        row = session.get(Request, (scope.scope_id, actor_id, key))
        if row is None:
            return None
        if row.request_hash != request_hash:
            _fail("IDEMPOTENCY_CONFLICT")
        return w.CachedResponse(status=row.response_status, body=row.response_json)

    def cached_request(self, scope, actor_id, key, request_hash):
        with self._session_factory() as session:
            return self._cached(session, scope, actor_id, key, request_hash)

    @staticmethod
    def _cache(session, scope, actor_id, key, request_hash, response, status):
        session.add(Request(scope_id=scope.scope_id, actor_id=actor_id, idempotency_key=key,
                            request_hash=request_hash, response_status=status,
                            response_json=response.model_dump(mode="json"), created_at=_now()))

    @staticmethod
    def _action(session, document, action, actor=None, reason=None, old=None, confirmation=None):
        session.add(Action(action_id=_id(), document_id=document.document_id, actor_id=actor,
                           action=action, reason=reason, old_revision=old, new_revision=document.revision,
                           confirmation_id=confirmation, created_at=_now()))

    @staticmethod
    def _touch(document):
        document.revision += 1
        document.updated_at = _now()

    def _invalidate(self, session, scope, scope_row, changed=None, *, source_changed=True):
        scope_row.generation += 1
        scope_row.updated_at = _now()
        for doc in self._documents(session, scope):
            if doc.document_type != "invoice":
                continue
            if doc.review_status == "completed":
                if source_changed and changed and (changed.document_id == doc.document_id or changed.document_id in doc.selected_document_ids):
                    if not doc.source_changed:
                        doc.source_changed = True
                        if doc is not changed:
                            self._touch(doc)
            elif doc.processing_status != "voided":
                doc.preview_stale = True
                if doc is not changed:
                    self._touch(doc)

    @staticmethod
    def _new_document(scope, kind, source, *, task_id=None, identity=None, actor=None):
        now = _now()
        return Document(document_id=_id(), tenant_id=scope.tenant_id, store_id=scope.store_id,
                        document_type=kind, source_kind=source, task_id=task_id, upstream_identity=identity,
                        revision=1, processing_status="processing", review_status="open" if kind == "invoice" else None,
                        selected_document_ids=[], match_status="waiting_counterpart", preview_stale=True,
                        source_changed=False, created_by=actor, created_at=now, updated_at=now)

    @staticmethod
    def _queue(session, task):
        now = _now()
        run = ExtractionRun(run_id=_id(), task_id=task.task_id, provider="disabled", model_name="disabled",
                            status="queued", started_at=now, created_at=now, next_attempt_at=now)
        session.add(ExtractionRunRow(**run.model_dump(mode="python")))
        task.status = "extracting"
        task.error_message = None
        task.updated_at = now
        return run.run_id

    def intake(self, scope, prepared, actor_id, key, request_hash):
        with self._session_factory.begin() as session:
            state = self._begin(session, scope)
            cached = self._cached(session, scope, actor_id, key, request_hash)
            if cached:
                return w.IntakeResponse.model_validate(cached.body)
            duplicate = session.scalar(select(Document).join(ExtractionTaskRow, Document.task_id == ExtractionTaskRow.task_id).where(
                Document.tenant_id == scope.tenant_id, Document.store_id == scope.store_id,
                Document.document_type == prepared.task.document_type, Document.processing_status != "voided",
                ExtractionTaskRow.sha256 == prepared.task.sha256).order_by(Document.created_at, Document.document_id))
            if duplicate:
                run = self._latest_run(session, duplicate.task_id)
                response = w.IntakeResponse(document=self._summary(session, duplicate), task_id=duplicate.task_id,
                                            run_id=run.run_id, duplicate=True)
            else:
                task = ExtractionTaskRow(**prepared.task.model_dump(mode="python"))
                session.add(task)
                session.flush()
                run_id = self._queue(session, task)
                doc = self._new_document(scope, prepared.task.document_type, "upload", task_id=task.task_id, actor=actor_id)
                session.add(doc)
                session.flush()
                self._action(session, doc, "uploaded", actor_id)
                self._invalidate(session, scope, state, doc)
                response = w.IntakeResponse(document=self._summary(session, doc), task_id=task.task_id,
                                            run_id=run_id, duplicate=False)
            self._cache(session, scope, actor_id, key, request_hash, response, 201)
            return response

    @staticmethod
    def _latest_run(session, task_id):
        return session.scalar(select(ExtractionRunRow).where(ExtractionRunRow.task_id == task_id).order_by(
            ExtractionRunRow.created_at.desc(), ExtractionRunRow.run_id.desc()).limit(1))

    @staticmethod
    def _revision(session, revision_id):
        row = session.get(Revision, revision_id) if revision_id else None
        return w.RevisionView(**_fields(row, w.RevisionView)) if row else None

    @staticmethod
    def _identity(version):
        return json.dumps([version.source_system, version.external_tenant_id, version.external_store_id,
                           version.external_receiving_id], ensure_ascii=False, separators=(",", ":"))

    def _latest_upstream(self, session, scope):
        rows = session.scalars(select(DocumentVersionRow).where(
            DocumentVersionRow.source_kind == "taptouch_receiving",
            DocumentVersionRow.external_tenant_id == scope.tenant_id,
            DocumentVersionRow.external_store_id == scope.store_id).order_by(DocumentVersionRow.external_version.desc()))
        latest = {}
        for row in rows:
            latest.setdefault(self._identity(row), row)
        return latest

    def _used(self, session, scope):
        docs = self._documents(session, scope)
        used = set(session.scalars(select(Claim.receive_document_id))) & {d.document_id for d in docs}
        legacy_versions = session.scalars(select(DocumentVersionRow).join(
            ReconciliationReceiveNoteRow, ReconciliationReceiveNoteRow.receive_note_version_id == DocumentVersionRow.version_id).where(
                DocumentVersionRow.source_kind == "taptouch_receiving",
                DocumentVersionRow.external_tenant_id == scope.tenant_id, DocumentVersionRow.external_store_id == scope.store_id))
        identities = {self._identity(v) for v in legacy_versions}
        used.update(d.document_id for d in docs if d.upstream_identity in identities)
        return used

    def _input(self, session, scope, doc):
        state = session.get(Scope, scope.scope_id)
        return w.PreviewInput(invoice=self._revision(session, doc.current_revision_id),
            receivings=[self._revision(session, d.current_revision_id) for d in self._documents(session, scope)
                        if d.document_type == "receive_note" and d.processing_status == "ready"],
            used_ids=self._used(session, scope), scope_generation=state.generation if state else 0,
            document_revision=doc.revision,
            manual_selection_ids=doc.selected_document_ids if doc.selection_origin == "manual" else None)

    @staticmethod
    def _proposal(input):
        proposal = select_candidates(input.invoice, input.receivings, input.used_ids)
        if input.manual_selection_ids is not None:
            # Never silently discard the user's explicit set when a source changes.
            proposal.selected_document_ids = sorted(input.manual_selection_ids)
            proposal.status = w.MatchStatus.SELECTED
        return proposal

    @staticmethod
    def _input_hash(input, ids):
        selected = [r for r in input.receivings if r.document_id in ids]
        ordered = sorted([input.invoice, *selected], key=lambda r: r.document_id)
        return _hash(dict(inputs=[dict(document_id=r.document_id, revision_id=r.revision_id,
                                       payload=r.payload.model_dump(mode="json")) for r in ordered],
                          selected_document_ids=sorted(ids),
                          selection_origin="manual" if input.manual_selection_ids is not None else "automatic",
                          rule_version=RULE, tolerances=TOLERANCES, scope_generation=input.scope_generation))

    def _result(self, session, scope, input, ids, computed=None):
        selected = [r for r in input.receivings if r.document_id in ids]
        result = computed.model_copy(deep=True) if computed is not None else compare_workspace(input.invoice, selected)
        blocks = list(result.blocking_codes)
        if len(selected) != len(ids):
            blocks.append(w.BlockingCode.SOURCE_VOIDED)
        if set(ids) & input.used_ids:
            blocks.append(w.BlockingCode.RECEIVING_IN_USE)
        number = normalize_identity(input.invoice.payload.document_number)
        supplier = input.invoice.payload.supplier
        if not number:
            blocks.append(w.BlockingCode.VALIDATION_BLOCKED)
        for doc in self._documents(session, scope):
            if doc.document_type != "invoice" or doc.document_id == input.invoice.document_id or doc.processing_status == "voided" or not doc.current_revision_id:
                continue
            other = self._revision(session, doc.current_revision_id)
            if normalize_identity(other.payload.document_number) == number and self._supplier_equal(supplier, other.payload.supplier):
                blocks.append(w.BlockingCode.DUPLICATE_INVOICE)
        result.blocking_codes = list(dict.fromkeys(blocks))
        if blocks:
            result.outcome = w.PreviewOutcome.BLOCKED
        return result

    @staticmethod
    def _supplier_equal(a, b):
        if a is None or b is None:
            return False
        aa, bb = normalize_identity(a.business_number or ""), normalize_identity(b.business_number or "")
        if not (aa and bb):
            aa, bb = normalize_identity(a.name or ""), normalize_identity(b.name or "")
        return bool(aa and bb and aa == bb)

    def pending_previews(self, scope, limit=100):
        with self._session_factory() as session:
            docs = [d for d in self._documents(session, scope) if d.document_type == "invoice"
                    and d.processing_status == "ready" and d.review_status != "completed" and d.preview_stale]
            return [self._input(session, scope, d) for d in sorted(docs, key=lambda d: (d.updated_at, d.document_id))[:max(0, min(limit, 100))]]

    def save_preview(self, scope, input, proposal, result):
        with self._session_factory.begin() as session:
            state = self._begin(session, scope)
            doc = self._document(session, scope, input.invoice.document_id)
            if doc.review_status == "completed" or doc.processing_status != "ready" or doc.revision != input.document_revision or state.generation != input.scope_generation:
                return False
            current = self._input(session, scope, doc)
            if current != input:
                return False
            ids = sorted(current.manual_selection_ids if current.manual_selection_ids is not None else proposal.selected_document_ids)
            if len(set(ids)) != len(ids) or (ids and result is None) or (not ids and result is not None):
                return False
            if current.manual_selection_ids is None and not set(ids).issubset({r.document_id for r in current.receivings}):
                return False
            doc.match_status = "selected" if ids else proposal.status
            if doc.selection_origin != "manual":
                doc.selected_document_ids = ids
                doc.selection_origin = "automatic" if ids else None
            doc.current_preview_id = None
            if ids:
                value = self._result(session, scope, current, ids, result)
                digest = self._input_hash(current, ids)
                preview = session.scalar(select(Preview).where(Preview.invoice_document_id == doc.document_id,
                    Preview.input_sha256 == digest, Preview.rule_version == RULE))
                if preview is None:
                    selected = sorted([r for r in current.receivings if r.document_id in ids], key=lambda r: r.document_id)
                    preview = Preview(preview_id=_id(), invoice_document_id=doc.document_id,
                        input_revision_ids=[current.invoice.revision_id, *[r.revision_id for r in selected]],
                        scope_generation=state.generation, selection_origin=doc.selection_origin,
                        rule_version=RULE, tolerances=TOLERANCES, input_sha256=digest,
                        result=value.model_dump(mode="json"), created_at=_now())
                    session.add(preview)
                    session.flush()
                doc.current_preview_id = preview.preview_id
            doc.preview_stale = False
            self._touch(doc)
            return True

    def _summary(self, session, doc, used=None):
        revision = self._revision(session, doc.current_revision_id)
        payload = revision.payload if revision else None
        status = doc.processing_status
        if status == "ready":
            if doc.document_type == "receive_note":
                if used is None:
                    used = self._used(session, w.WorkspaceScopeKey(tenant_id=doc.tenant_id, store_id=doc.store_id))
                status = "completed" if doc.document_id in used else "waiting_counterpart"
            elif doc.review_status == "completed":
                status = "completed"
            elif doc.preview_stale:
                status = "processing"
            elif doc.review_status == "investigating":
                status = "needs_attention"
            elif doc.match_status == "waiting_counterpart":
                status = "waiting_counterpart"
            else:
                preview = session.get(Preview, doc.current_preview_id) if doc.current_preview_id else None
                status = "needs_attention" if doc.match_status == "needs_selection" or (preview and preview.result["outcome"] != "consistent") else "awaiting_confirmation"
        return w.DocumentSummary(**_fields(doc, w.DocumentSummary), display_status=status,
            document_number=payload.document_number if payload else None,
            supplier_name=payload.supplier.name if payload and payload.supplier else None,
            document_date=payload.document_date if payload else None)

    def list_documents(self, scope, query):
        with self._session_factory() as session:
            used = self._used(session, scope)
            docs = [d for d in self._documents(session, scope) if d.document_type == query.type]
            docs.sort(key=lambda d: d.document_id)
            docs.sort(key=lambda d: d.updated_at, reverse=True)
            items = [self._summary(session, d, used) for d in docs]
            if query.status:
                items = [i for i in items if i.display_status in query.status]
            if query.q:
                q = query.q.casefold()
                items = [i for i in items if q in (i.document_number or "").casefold() or q in (i.supplier_name or "").casefold()]
            offset = (query.page - 1) * query.page_size
            return w.DocumentPage(items=items[offset:offset + query.page_size], total=len(items), page=query.page, page_size=query.page_size)

    @staticmethod
    def _actions(session, document_id):
        return [w.ActionView(**_fields(a, w.ActionView)) for a in session.scalars(select(Action).where(
            Action.document_id == document_id).order_by(Action.created_at.desc(), Action.action_id.desc()))]

    def get_actions(self, scope, document_id, page, page_size):
        query = w.PageQuery(page=page, page_size=page_size)
        with self._session_factory() as session:
            self._document(session, scope, document_id)
            actions = self._actions(session, document_id)
            offset = (query.page - 1) * query.page_size
            return w.ActionPage(items=actions[offset:offset + page_size], total=len(actions), **query.model_dump())

    def _confirmation(self, session, scope, confirmation_id):
        row = session.get(Confirmation, confirmation_id)
        if row is None:
            _fail("DOCUMENT_NOT_FOUND")
        self._document(session, scope, row.invoice_document_id)
        invoice = self._revision(session, row.invoice_revision_id)
        receives = [self._revision(session, rid) for rid in row.receive_revision_ids]
        return w.ConfirmationView(**_fields(row, w.ConfirmationView),
            invoice_number=invoice.payload.document_number,
            receive_note_numbers=[r.payload.document_number for r in receives],
            input_revision_ids=[row.invoice_revision_id, *row.receive_revision_ids])

    def get_confirmation(self, scope, confirmation_id):
        with self._session_factory() as session:
            return self._confirmation(session, scope, confirmation_id)

    def get_document(self, scope, document_id):
        with self._session_factory() as session:
            doc = self._document(session, scope, document_id)
            preview = session.get(Preview, doc.current_preview_id) if doc.current_preview_id else None
            input = self._input(session, scope, doc) if doc.current_revision_id and doc.document_type == "invoice" else None
            selected_documents = [self._document(session, scope, i) for i in doc.selected_document_ids]
            selected = [self._revision(session, selected_document.current_revision_id) for selected_document in selected_documents]
            used = self._used(session, scope)
            related_invoices = []
            if doc.document_type == "receive_note":
                related_invoices = [
                    self._summary(session, invoice, used)
                    for invoice in sorted(self._documents(session, scope), key=lambda row: row.document_id)
                    if invoice.document_type == "invoice"
                    and invoice.processing_status != "voided"
                    and doc.document_id in invoice.selected_document_ids
                ]
            return w.DocumentDetail(document=self._summary(session, doc, used), review_status=doc.review_status,
                match_status=doc.match_status, selection_origin=doc.selection_origin, selection_note=doc.selection_note,
                current_revision=self._revision(session, doc.current_revision_id),
                candidates=select_candidates(input.invoice, input.receivings, input.used_ids).candidates if input else [],
                selected_receivings=[r for r in selected if r],
                selected_receiving_source_ids=[selected_document.document_id for selected_document in selected_documents
                                               if selected_document.source_kind == "upload"],
                related_invoices=related_invoices,
                preview=w.PreviewView(**_fields(preview, w.PreviewView)) if preview else None,
                preview_stale=doc.preview_stale,
                confirmation=self._confirmation(session, scope, doc.current_confirmation_id) if doc.current_confirmation_id else None,
                actions=self._actions(session, document_id)[:50], source_url_available=doc.source_kind == "upload")

    def source_metadata(self, scope, document_id):
        with self._session_factory() as session:
            doc = self._document(session, scope, document_id)
            if doc.source_kind != "upload":
                _fail("DOCUMENT_NOT_FOUND")
            task = session.get(ExtractionTaskRow, doc.task_id)
            return w.SourceMetadata(filename=task.original_filename, content_type=task.content_type, object_key=task.storage_object_key)

    def runtime(self, scope):
        with self._session_factory() as session:
            state = session.get(Scope, scope.scope_id)
            last = state.last_sync_at if state else None
            now = _now()
            online = last is not None and (now - last).total_seconds() <= 15
            docs = [d for d in self._documents(session, scope) if d.document_type == "invoice"
                    and d.review_status != "completed" and d.processing_status != "voided" and d.preview_stale]
            lag = max(0, int((now - min(d.updated_at for d in docs)).total_seconds())) if docs else 0
            return w.RuntimeView(enabled=True, worker_online=online, last_sync_at=last,
                                 preview_lag_seconds=lag if online else None)

    def _append_revision(self, session, doc, payload, *, origin, draft=None, version=None,
                         evidence=None, issues=None, actor=None, reason=None):
        old = session.get(Revision, doc.current_revision_id) if doc.current_revision_id else None
        row = Revision(revision_id=_id(), document_id=doc.document_id, sequence=old.sequence + 1 if old else 1,
            source_draft_id=draft, source_version_id=version, payload=payload,
            evidence=evidence or [], validation_issues=issues or [], content_sha256=_hash(payload),
            origin=origin, actor_id=actor, reason=reason, created_at=_now(),
            evidence_origin_revision_id=(old.evidence_origin_revision_id or old.revision_id) if origin == "manual" and old else None)
        session.add(row)
        session.flush()
        doc.current_revision_id = row.revision_id
        doc.error_code = None
        doc.processing_status = "ready"
        self._touch(doc)
        return row

    def sync_sources(self, scope):
        with self._session_factory.begin() as session:
            state = self._begin(session, scope)
            changed = 0
            state.last_error_code = None
            docs = self._documents(session, scope)
            known = {d.upstream_identity: d for d in docs if d.upstream_identity}
            for identity, version in self._latest_upstream(session, scope).items():
                doc = known.get(identity)
                if doc is None and version.record_status == "voided":
                    continue
                try:
                    with session.begin_nested():
                        if doc is None:
                            doc = self._new_document(scope, "receive_note", "taptouch", identity=identity)
                            session.add(doc)
                            session.flush()
                        old = session.get(Revision, doc.current_revision_id) if doc.current_revision_id else None
                        if old and old.source_version_id == version.version_id:
                            continue
                        previous = doc.revision
                        payload = version.document_json
                        view = w.RevisionView(revision_id=_id(), document_id=doc.document_id, sequence=1,
                            origin="upstream", payload=payload, created_at=_now())
                        issues = [i.model_dump(mode="json") for i in ValidationService().validate(view.payload).issues]
                        self._append_revision(session, doc, payload, origin="upstream", version=version.version_id, issues=issues)
                        if version.record_status == "voided":
                            doc.processing_status = "voided"
                        self._action(session, doc, "source_updated", old=previous)
                        session.flush()
                        self._invalidate(session, scope, state, doc)
                        changed += 1
                except Exception:
                    logger.exception("Workspace upstream synchronization failed", extra={"code": "SOURCE_REVIEW_REQUIRED"})
                    state.last_error_code = "SOURCE_REVIEW_REQUIRED"
                    if doc is not None and doc in session:
                        doc.error_code = "SOURCE_REVIEW_REQUIRED"
            for doc in docs:
                if doc.source_kind != "upload" or doc.processing_status == "voided":
                    continue
                try:
                    with session.begin_nested():
                        if self._sync_upload(session, scope, state, doc):
                            changed += 1
                except Exception:
                    logger.exception("Workspace upload synchronization failed", extra={"document_id": doc.document_id})
                    doc.error_code = "SOURCE_REVIEW_REQUIRED"
                    state.last_error_code = "SOURCE_REVIEW_REQUIRED"
            state.last_sync_at = _now()
            state.updated_at = _now()
            session.flush()
            return w.SyncSummary(changed_documents=changed, scope_generation=state.generation)

    def _sync_upload(self, session, scope, state, doc):
        run = self._latest_run(session, doc.task_id)
        if run is None:
            return False
        draft = session.scalar(select(DocumentDraftRow).where(DocumentDraftRow.run_id == run.run_id))
        old = session.get(Revision, doc.current_revision_id) if doc.current_revision_id else None
        source_revision = (session.get(Revision, old.evidence_origin_revision_id)
                           if old and old.origin == "manual" and old.evidence_origin_revision_id else old)
        if (old and draft and run.status in {"ready_for_review", "succeeded"} and old.source_draft_id == draft.draft_id
                and source_revision and source_revision.content_sha256 == _hash(draft.normalized_json)):
            if doc.error_code is not None:
                doc.error_code = None
                self._touch(doc)
                return True
            return False
        if old and old.origin == "manual":
            if doc.error_code != "SOURCE_REVIEW_REQUIRED":
                doc.error_code = "SOURCE_REVIEW_REQUIRED"
                self._touch(doc)
                self._invalidate(session, scope, state, doc)
                return True
            return False
        if draft is not None and run.status in {"ready_for_review", "succeeded"}:
            evidence = [FieldEvidence(**_fields(e, FieldEvidence)).model_dump(mode="json") for e in session.scalars(
                select(FieldEvidenceRow).where(FieldEvidenceRow.draft_id == draft.draft_id).order_by(FieldEvidenceRow.evidence_id))]
            issues = [ValidationIssue(**_fields(i, ValidationIssue)).model_dump(mode="json") for i in session.scalars(
                select(ValidationIssueRow).where(ValidationIssueRow.draft_id == draft.draft_id).order_by(ValidationIssueRow.issue_id))]
            old_revision = doc.revision
            self._append_revision(session, doc, draft.normalized_json, origin="extracted", draft=draft.draft_id,
                                  evidence=evidence, issues=issues)
            self._action(session, doc, "extracted", old=old_revision)
            session.flush()
            self._invalidate(session, scope, state, doc)
            return True
        status = run.status if run.status in {"failed", "cancelled"} else "processing"
        error = (run.phase_error_code or "SOURCE_REVIEW_REQUIRED") if status == "failed" else None
        if doc.processing_status != status or doc.error_code != error:
            doc.processing_status, doc.error_code = status, error
            self._touch(doc)
            session.flush()
            self._invalidate(session, scope, state, doc)
            return True
        return False

    def _sources_current(self, session, scope, docs):
        latest = self._latest_upstream(session, scope)
        # Newly arrived upstream identities also invalidate an automatic selection.
        known = {d.upstream_identity: d for d in self._documents(session, scope) if d.upstream_identity}
        for identity, version in latest.items():
            if identity not in known:
                if version.record_status != "voided":
                    return False
                continue
            current = session.get(Revision, known[identity].current_revision_id) if known[identity].current_revision_id else None
            if current is None or current.source_version_id != version.version_id:
                return False
        # An unprojected ready upload can change the automatic candidate set too.
        for candidate in self._documents(session, scope):
            if candidate.source_kind != "upload" or candidate.processing_status == "voided":
                continue
            run = self._latest_run(session, candidate.task_id)
            draft = session.scalar(select(DocumentDraftRow).where(DocumentDraftRow.run_id == run.run_id)) if run else None
            current = session.get(Revision, candidate.current_revision_id) if candidate.current_revision_id else None
            source_revision = (session.get(Revision, current.evidence_origin_revision_id)
                               if current and current.origin == "manual" and current.evidence_origin_revision_id else current)
            if draft is not None and run.status in {"ready_for_review", "succeeded"} and (
                    current is None or current.source_draft_id != draft.draft_id or source_revision is None
                    or source_revision.content_sha256 != _hash(draft.normalized_json)):
                return False
        for doc in docs:
            if doc.processing_status != "ready" or not doc.current_revision_id or doc.error_code == "SOURCE_REVIEW_REQUIRED":
                return False
            revision = session.get(Revision, doc.current_revision_id)
            if doc.source_kind == "upload":
                run = self._latest_run(session, doc.task_id)
                draft = session.scalar(select(DocumentDraftRow).where(DocumentDraftRow.run_id == run.run_id)) if run else None
                if run is None or run.status not in {"ready_for_review", "succeeded"} or draft is None or draft.draft_id != revision.source_draft_id:
                    return False
        return True

    def _select(self, session, scope, doc, command):
        if doc.document_type != "invoice" or doc.processing_status != "ready" or doc.review_status == "completed":
            _fail("INVALID_TRANSITION", doc)
        invoice = self._revision(session, doc.current_revision_id)
        used = self._used(session, scope)
        for document_id in command.receive_document_ids:
            receiving = self._document(session, scope, document_id)
            if receiving.document_type != "receive_note" or receiving.processing_status != "ready":
                _fail("SOURCE_VOIDED" if receiving.processing_status == "voided" else "INVALID_TRANSITION", doc)
            if document_id in used:
                _fail("RECEIVING_IN_USE", doc)
            payload = self._revision(session, receiving.current_revision_id).payload
            if not self._supplier_equal(invoice.payload.supplier, payload.supplier) or invoice.payload.currency != payload.currency:
                _fail("SUBJECT_CONFLICT", doc)
        doc.selected_document_ids = sorted(command.receive_document_ids)
        doc.selection_origin = "manual" if command.receive_document_ids else None
        doc.selection_note = command.reason if command.receive_document_ids else None
        doc.preview_stale = True
        doc.current_preview_id = None

    def _confirm(self, session, scope, state, doc, command, actor):
        if doc.document_type != "invoice" or doc.processing_status != "ready" or doc.review_status == "completed":
            _fail("INVALID_TRANSITION", doc)
        # Explicitly report occupied frozen selections, even if the generation is stale.
        if set(doc.selected_document_ids) & self._used(session, scope):
            _fail("RECEIVING_IN_USE", doc)
        preview = session.get(Preview, doc.current_preview_id) if doc.current_preview_id else None
        if doc.preview_stale or preview is None or preview.preview_id != command.preview_id or preview.scope_generation != state.generation:
            _fail("PREVIEW_STALE", doc)
        docs = [doc, *[self._document(session, scope, i) for i in doc.selected_document_ids]]
        if not self._sources_current(session, scope, docs):
            _fail("PREVIEW_STALE", doc)
        input = self._input(session, scope, doc)
        proposal = self._proposal(input)
        if not proposal.selected_document_ids:
            _fail("UNRESOLVED_MATCH", doc)
        if proposal.selected_document_ids != doc.selected_document_ids or self._input_hash(input, doc.selected_document_ids) != preview.input_sha256:
            _fail("PREVIEW_STALE", doc)
        result = self._result(session, scope, input, doc.selected_document_ids)
        if result.model_dump(mode="json") != preview.result:
            _fail("PREVIEW_STALE", doc)
        if result.outcome == "blocked":
            code = "DUPLICATE_INVOICE" if "DUPLICATE_INVOICE" in result.blocking_codes else "VALIDATION_BLOCKED"
            _fail(code, doc)
        if set(result.unverified_dimensions) != set(command.acknowledged_unverified_dimensions):
            _fail("UNVERIFIED_NOT_ACKNOWLEDGED", doc)
        expected = "matched" if result.outcome == "consistent" else "resolved_with_note"
        if command.resolution != expected or (expected == "resolved_with_note" and not command.note):
            _fail("RESOLUTION_NOTE_REQUIRED", doc)
        row = Confirmation(confirmation_id=_id(), invoice_document_id=doc.document_id,
            preview_id=preview.preview_id, invoice_revision_id=preview.input_revision_ids[0],
            receive_revision_ids=preview.input_revision_ids[1:], result_snapshot=preview.result,
            rule_version=preview.rule_version, tolerances=preview.tolerances, input_sha256=preview.input_sha256,
            actor_id=actor, resolution=command.resolution, note=command.note,
            acknowledged_unverified_dimensions=command.acknowledged_unverified_dimensions, created_at=_now())
        session.add(row)
        session.flush()
        for document_id in doc.selected_document_ids:
            session.add(Claim(receive_document_id=document_id, invoice_document_id=doc.document_id,
                              confirmation_id=row.confirmation_id, created_at=_now()))
        doc.review_status = "completed"
        doc.current_confirmation_id = row.confirmation_id
        doc.source_changed = False
        return row.confirmation_id

    def mutate(self, scope, document_id, operation, command, actor_id, key, request_hash):
        # A rejected stale confirmation leaves only the recomputation marker in a
        # separate transaction. No failed request, action or business mutation survives.
        try:
            return self._mutate(scope, document_id, operation, command, actor_id, key, request_hash)
        except w.WorkspaceError as exc:
            if exc.detail.code == w.WorkspaceErrorCode.PREVIEW_STALE:
                with self._session_factory.begin() as session:
                    self._begin(session, scope)
                    doc = self._document(session, scope, document_id)
                    if doc.review_status != "completed":
                        doc.preview_stale = True
            raise

    def _mutate(self, scope, document_id, operation, command, actor_id, key, request_hash):
        commands = {"edit": w.EditCommand, "select": w.SelectionCommand, "investigate": w.InvestigateCommand,
                    "confirm": w.ConfirmCommand, "reopen": w.ReasonCommand, "void": w.ReasonCommand, "retry": w.RevisionCommand}
        if operation not in commands or type(command) is not commands[operation]:
            _fail("INVALID_REQUEST")
        with self._session_factory.begin() as session:
            state = self._begin(session, scope)
            cached = self._cached(session, scope, actor_id, key, request_hash)
            if cached:
                cls = w.ConfirmationResponse if operation == "confirm" else w.RetryResponse if operation == "retry" else w.DocumentSummary
                return cls.model_validate(cached.body)
            doc = self._document(session, scope, document_id)
            if operation == "confirm" and set(doc.selected_document_ids) & self._used(session, scope):
                _fail("RECEIVING_IN_USE", doc)
            if doc.revision != command.expected_revision:
                _fail("REVISION_CONFLICT", doc)
            old = doc.revision
            confirmation_id = None
            reason = getattr(command, "reason", getattr(command, "note", None))
            advances_generation = operation in {"edit", "confirm", "reopen", "void"}
            if operation == "edit":
                if doc.source_kind != "upload" or doc.processing_status != "ready" or doc.review_status == "completed" or doc.document_id in self._used(session, scope):
                    _fail("INVALID_TRANSITION", doc)
                if command.document.document_type != doc.document_type:
                    _fail("INVALID_REQUEST", doc)
                prior = session.get(Revision, doc.current_revision_id)
                issues = [i.model_dump(mode="json") for i in ValidationService().validate(command.document).issues]
                self._append_revision(session, doc, command.document.model_dump(mode="json"), origin="manual",
                    draft=prior.source_draft_id, evidence=prior.evidence, issues=issues, actor=actor_id, reason=reason)
                doc.preview_stale = True
            elif operation == "select":
                self._select(session, scope, doc, command)
            elif operation == "investigate":
                if doc.document_type != "invoice" or doc.processing_status != "ready" or doc.review_status == "completed":
                    _fail("INVALID_TRANSITION", doc)
                doc.review_status = "investigating"
            elif operation == "confirm":
                confirmation_id = self._confirm(session, scope, state, doc, command, actor_id)
            elif operation == "reopen":
                if doc.document_type != "invoice" or doc.review_status != "completed":
                    _fail("INVALID_TRANSITION", doc)
                confirmation_id = doc.current_confirmation_id
                session.execute(delete(Claim).where(Claim.invoice_document_id == doc.document_id))
                doc.current_confirmation_id = None
                doc.review_status = "open"
                doc.source_changed = False
                doc.preview_stale = True
            elif operation == "void":
                if doc.source_kind != "upload" or doc.processing_status == "voided" or doc.review_status == "completed":
                    _fail("INVALID_TRANSITION", doc)
                if doc.document_id in self._used(session, scope):
                    _fail("RECEIVING_IN_USE", doc)
                doc.processing_status = "voided"
                doc.preview_stale = True
            elif operation == "retry":
                if doc.source_kind != "upload" or doc.processing_status not in {"failed", "cancelled"} or doc.current_revision_id:
                    _fail("INVALID_TRANSITION", doc)
                if session.scalar(select(DocumentDraftRow.draft_id).where(DocumentDraftRow.task_id == doc.task_id).limit(1)):
                    _fail("SOURCE_REVIEW_REQUIRED", doc)
                active = session.scalar(select(ExtractionRunRow.run_id).where(ExtractionRunRow.task_id == doc.task_id,
                    ExtractionRunRow.status.not_in(["failed", "cancelled", "ready_for_review", "succeeded"])).limit(1))
                if active:
                    _fail("INVALID_TRANSITION", doc)
                task = session.get(ExtractionTaskRow, doc.task_id)
                run_id = self._queue(session, task)
                doc.processing_status = "processing"
                doc.error_code = None
            if operation != "edit":
                self._touch(doc)
            actions = dict(edit="edited", select="selection_changed", investigate="investigating", confirm="confirmed",
                           reopen="reopened", void="voided", retry="retry_requested")
            self._action(session, doc, actions[operation], actor_id, reason, old, confirmation_id)
            session.flush()
            if advances_generation:
                self._invalidate(session, scope, state, doc, source_changed=operation not in {"confirm", "reopen"})
            summary = self._summary(session, doc)
            response = (w.ConfirmationResponse(document=summary, confirmation=self._confirmation(session, scope, confirmation_id))
                        if operation == "confirm" else w.RetryResponse(document=summary, run_id=run_id)
                        if operation == "retry" else summary)
            self._cache(session, scope, actor_id, key, request_hash, response,
                        201 if operation == "confirm" else 202 if operation == "retry" else 200)
            return response
