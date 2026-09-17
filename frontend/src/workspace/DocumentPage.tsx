import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ApiError } from "../api/client";
import { label, systemMessage } from "../i18n";
import { StructuredDocumentEditor } from "../review/StructuredDocumentEditor";
import {
  confirm,
  createIdempotencyKey,
  editDocument,
  exportConfirmation,
  getActions,
  getDocument,
  investigate,
  listDocuments,
  reopen,
  retry,
  selectReceivings,
  voidDocument,
} from "./workspaceClient";
import { canConfirm, canEdit, canReopen, displayStatusLabel, metricStatusLabel, unverifiedSummary } from "./workspacePresentation";
import type {
  ActionView,
  Candidate,
  DocumentDetail,
  DocumentPayload,
  DocumentSummary,
  RevisionView,
} from "./workspaceTypes";

type RetryOperation = { label: string; key: string; run: () => Promise<void> };
type ManualResult = { summary: DocumentSummary; detail: DocumentDetail; eligible: boolean; reason: string };
type SourcePreview = { status: "idle" | "loading" | "ready" | "error"; url: string; type: string };

function useDocumentSource(documentId: string | null, available: boolean): SourcePreview {
  const [source, setSource] = useState<SourcePreview>({ status: "idle", url: "", type: "" });
  useEffect(() => {
    let active = true;
    let objectUrl = "";
    setSource({ status: available ? "loading" : "idle", url: "", type: "" });
    if (!documentId || !available) return;
    void fetch(`/api/workspace/documents/${encodeURIComponent(documentId)}/source`, { credentials: "include" })
      .then(async (response) => {
        if (!response.ok) throw new Error("无法加载原件");
        const blob = await response.blob();
        if (!active) return;
        objectUrl = URL.createObjectURL(blob);
        setSource({ status: "ready", url: objectUrl, type: blob.type });
      })
      .catch(() => { if (active) setSource({ status: "error", url: "", type: "" }); });
    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [available, documentId]);
  return source;
}

function SourceViewer({ source, unavailableText }: { source: SourcePreview; unavailableText: string }) {
  if (source.status === "idle") return <div className="empty-state">{unavailableText}</div>;
  if (source.status === "loading") return <div className="empty-state">正在安全加载原件…</div>;
  if (source.status === "error") return <div className="error-banner">无法加载原件，请刷新后重试。</div>;
  return source.type.startsWith("image/")
    ? <img alt="单据原件" className="workspace-source-image" src={source.url} />
    : <iframe className="workspace-source-frame" src={source.url} title="单据 PDF 原件" />;
}

function normalized(value: string | null | undefined): string {
  return (value ?? "").normalize("NFKC").toLocaleLowerCase().replace(/[^\p{L}\p{N}]/gu, "");
}

function subjectEligible(invoice: DocumentPayload, receiving: DocumentPayload): { eligible: boolean; reason: string } {
  const invoiceBusiness = normalized(invoice.supplier?.business_number);
  const receiveBusiness = normalized(receiving.supplier?.business_number);
  const supplierEqual = invoiceBusiness && receiveBusiness
    ? invoiceBusiness === receiveBusiness
    : Boolean(normalized(invoice.supplier?.name)) && normalized(invoice.supplier?.name) === normalized(receiving.supplier?.name);
  if (!supplierEqual) return { eligible: false, reason: "供应商主体不一致或无法核验" };
  if (invoice.currency !== receiving.currency) return { eligible: false, reason: "币种不一致" };
  return { eligible: true, reason: "同供应商、同币种，可人工选择" };
}

function candidateDisabled(candidate: Candidate): boolean {
  return !candidate.eligible || candidate.already_used || candidate.reason_codes.some((code) =>
    ["SUPPLIER_CONFLICT", "SUPPLIER_UNVERIFIED", "CURRENCY_CONFLICT", "RECEIVING_IN_USE", "SOURCE_VOIDED"].includes(code),
  );
}

function payloadSummary(payload: DocumentPayload) {
  return [
    ["单据编号", payload.document_number],
    ["单据日期", payload.document_date ?? "—"],
    ["采购订单号", payload.purchase_order_number ?? "—"],
    ["供应商", payload.supplier?.name ?? "—"],
    ["企业注册号", payload.supplier?.business_number ?? "—"],
    ["币种", payload.currency],
    ["总额", payload.total ?? "—"],
  ] as const;
}

export function DocumentPage({
  allowAdvancedJson = false,
  autoOpenRelated = false,
  documentId,
  onNavigate,
}: {
  allowAdvancedJson?: boolean;
  autoOpenRelated?: boolean;
  documentId: string;
  onNavigate: (path: string, replace?: boolean) => void;
}) {
  const [detail, setDetail] = useState<DocumentDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState("");
  const [editor, setEditor] = useState("");
  const [editorDirty, setEditorDirty] = useState(false);
  const [editReason, setEditReason] = useState("");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [selectionDirty, setSelectionDirty] = useState(false);
  const [selectionReason, setSelectionReason] = useState("");
  const [investigateNote, setInvestigateNote] = useState("");
  const [resolutionNote, setResolutionNote] = useState("");
  const [acknowledged, setAcknowledged] = useState(false);
  const [reopenReason, setReopenReason] = useState("");
  const [voidReason, setVoidReason] = useState("");
  const [manualQuery, setManualQuery] = useState("");
  const [manualResults, setManualResults] = useState<ManualResult[]>([]);
  const [manualSearching, setManualSearching] = useState(false);
  const [showSelectionTools, setShowSelectionTools] = useState(false);
  const [showStructuredFields, setShowStructuredFields] = useState(false);
  const [olderActions, setOlderActions] = useState<ActionView[]>([]);
  const [actionsPage, setActionsPage] = useState(2);
  const [actionsTotal, setActionsTotal] = useState<number | null>(null);
  const [activeReceivingId, setActiveReceivingId] = useState<string | null>(null);
  const retryOperation = useRef<RetryOperation | null>(null);
  const initialized = useRef(false);
  const editorDirtyRef = useRef(false);
  const selectionDirtyRef = useRef(false);
  const activeDocumentId = useRef(documentId);

  const applyServerDetail = useCallback((next: DocumentDetail, resetDrafts = false) => {
    setDetail(next);
    if (!initialized.current || resetDrafts || !editorDirtyRef.current) {
      setEditor(next.current_revision ? JSON.stringify(next.current_revision.payload, null, 2) : "");
      if (resetDrafts) {
        setEditorDirty(false);
        editorDirtyRef.current = false;
        setEditReason("");
      }
    }
    if (!initialized.current || resetDrafts || !selectionDirtyRef.current) {
      setSelectedIds(next.document.selected_document_ids);
      if (resetDrafts) {
        setSelectionDirty(false);
        selectionDirtyRef.current = false;
        setSelectionReason("");
      }
      initialized.current = true;
    }
  }, []);

  const refresh = useCallback(async (resetDrafts = false) => {
    try {
      const next = await getDocument(documentId);
      if (activeDocumentId.current !== documentId) return;
      applyServerDetail(next, resetDrafts);
      setLoadError("");
    } catch (problem) {
      if (activeDocumentId.current !== documentId) return;
      setLoadError(problem instanceof Error ? problem.message : "无法加载单据");
    } finally {
      if (activeDocumentId.current === documentId) setLoading(false);
    }
  }, [applyServerDetail, documentId]);

  useEffect(() => {
    activeDocumentId.current = documentId;
    initialized.current = false;
    setDetail(null);
    setLoading(true);
    setLoadError("");
    setMessage("");
    setBusy("");
    setEditor("");
    setEditorDirty(false);
    editorDirtyRef.current = false;
    setEditReason("");
    setSelectedIds([]);
    setSelectionDirty(false);
    selectionDirtyRef.current = false;
    setSelectionReason("");
    setInvestigateNote("");
    setResolutionNote("");
    setAcknowledged(false);
    setReopenReason("");
    setVoidReason("");
    setManualQuery("");
    setManualResults([]);
    setShowSelectionTools(false);
    setShowStructuredFields(false);
    setOlderActions([]);
    setActionsPage(2);
    setActionsTotal(null);
    setActiveReceivingId(null);
    retryOperation.current = null;
    void refresh(true);
  }, [documentId, refresh]);

  useEffect(() => {
    if (!detail) return;
    const tick = () => { if (!document.hidden) void refresh(false); };
    const unfinishedInvoice = detail.document.document_type === "invoice"
      && detail.review_status !== "completed"
      && detail.document.processing_status !== "voided";
    const shouldPoll = detail.document.processing_status === "processing"
      || detail.preview_stale
      || unfinishedInvoice
      || (autoOpenRelated && detail.document.document_type === "receive_note" && detail.related_invoices.length === 0);
    const interval = shouldPoll ? window.setInterval(tick, 3_000) : null;
    const visible = () => { if (!document.hidden) void refresh(false); };
    document.addEventListener("visibilitychange", visible);
    return () => {
      if (interval !== null) window.clearInterval(interval);
      document.removeEventListener("visibilitychange", visible);
    };
  }, [autoOpenRelated, detail?.document.document_type, detail?.document.processing_status, detail?.preview_stale, detail?.related_invoices.length, detail?.review_status, refresh]);

  useEffect(() => {
    if (!autoOpenRelated || detail?.document.document_type !== "receive_note") return;
    if (detail.related_invoices.length !== 1) return;
    onNavigate(`/documents/${encodeURIComponent(detail.related_invoices[0].document_id)}?view=compare`, true);
  }, [autoOpenRelated, detail?.document.document_type, detail?.related_invoices, onNavigate]);

  async function execute(operation: RetryOperation) {
    setBusy(operation.label);
    setMessage("");
    try {
      await operation.run();
      retryOperation.current = null;
    } catch (problem) {
      if (problem instanceof ApiError) {
        retryOperation.current = null;
        if (problem.status === 409) {
          await refresh(false);
          setMessage(`${problem.message}。已加载最新详情；未保存的字段、选择和备注仍保留，请重新核对后再提交。`);
          return;
        }
      } else {
        retryOperation.current = operation;
      }
      setMessage(problem instanceof Error ? problem.message : `${operation.label}失败`);
      throw problem;
    } finally {
      setBusy("");
    }
  }

  function startOperation(labelText: string, submit: (key: string) => Promise<void>) {
    const key = createIdempotencyKey();
    const operation: RetryOperation = { label: labelText, key, run: () => submit(key) };
    void execute(operation).catch(() => undefined);
  }

  async function searchManualReceivings() {
    if (!detail?.current_revision) return;
    const requestDocumentId = documentId;
    setManualSearching(true);
    setMessage("");
    try {
      const page = await listDocuments({ type: "receive_note", q: manualQuery.trim() || null, page: 1, page_size: 100 });
      const ready = page.items.filter((item) => item.processing_status === "ready");
      const details = await Promise.all(ready.map((item) => getDocument(item.document_id)));
      if (activeDocumentId.current !== requestDocumentId) return;
      setManualResults(details.map((itemDetail) => {
        const summary = ready.find((item) => item.document_id === itemDetail.document.document_id)!;
        if (summary.display_status === "completed" && !selectedIds.includes(summary.document_id)) {
          return { summary, detail: itemDetail, eligible: false, reason: "已被正式结果占用" };
        }
        if (!itemDetail.current_revision) return { summary, detail: itemDetail, eligible: false, reason: "尚无可用结构化版本" };
        const check = subjectEligible(detail.current_revision!.payload, itemDetail.current_revision.payload);
        return { summary, detail: itemDetail, ...check };
      }));
    } catch (problem) {
      if (activeDocumentId.current !== requestDocumentId) return;
      setMessage(problem instanceof Error ? problem.message : "无法搜索收货记录");
    } finally {
      setManualSearching(false);
    }
  }

  async function loadOlderActions() {
    if (!detail) return;
    const requestDocumentId = documentId;
    try {
      const page = await getActions(documentId, { page: actionsPage, page_size: 50 });
      if (activeDocumentId.current !== requestDocumentId) return;
      setOlderActions((current) => [...current, ...page.items]);
      setActionsPage((value) => value + 1);
      setActionsTotal(page.total);
    } catch (problem) {
      if (activeDocumentId.current !== requestDocumentId) return;
      setMessage(problem instanceof Error ? problem.message : "无法加载更早审计记录");
    }
  }

  const allActions = useMemo(() => [...(detail?.actions ?? []), ...olderActions], [detail?.actions, olderActions]);
  const selectedRevisions = useMemo(() => {
    const byId = new Map<string, RevisionView>();
    for (const revision of detail?.selected_receivings ?? []) byId.set(revision.document_id, revision);
    for (const result of manualResults) if (result.detail.current_revision) byId.set(result.summary.document_id, result.detail.current_revision);
    return selectedIds.map((id) => byId.get(id)).filter((value): value is RevisionView => Boolean(value));
  }, [detail?.selected_receivings, manualResults, selectedIds]);

  const selectedSourceIds = useMemo(() => {
    const ids = new Set(detail?.selected_receiving_source_ids ?? []);
    for (const result of manualResults) {
      if (result.detail.source_url_available) ids.add(result.summary.document_id);
    }
    return ids;
  }, [detail?.selected_receiving_source_ids, manualResults]);

  useEffect(() => {
    if (selectedRevisions.some((revision) => revision.document_id === activeReceivingId)) return;
    setActiveReceivingId(selectedRevisions[0]?.document_id ?? null);
  }, [activeReceivingId, selectedRevisions]);

  const activeReceiving = selectedRevisions.find((revision) => revision.document_id === activeReceivingId) ?? null;
  const source = useDocumentSource(documentId, Boolean(detail?.source_url_available));
  const receivingSource = useDocumentSource(
    activeReceiving?.document_id ?? null,
    Boolean(activeReceiving && selectedSourceIds.has(activeReceiving.document_id)),
  );

  useEffect(() => {
    setAcknowledged(false);
  }, [detail?.document.revision, detail?.preview?.preview_id, selectedIds.slice().sort().join("|")]);

  if (loading) return <div className="loading">正在加载单据…</div>;
  if (!detail) return <section className="page"><button className="back-link" onClick={() => onNavigate("/")}>← 返回工作台</button><div className="error-banner">{loadError || "未找到单据"}</div></section>;

  const isInvoice = detail.document.document_type === "invoice";
  const editable = canEdit(detail);
  const confirmable = detail.document.source_kind === "upload" && canConfirm(detail) && !editorDirty && !selectionDirty;
  const preview = detail.preview?.result;
  const outcome = preview?.outcome;
  const completed = detail.document.display_status === "completed";
  const mutableInvoice = isInvoice && detail.document.source_kind === "upload" && !completed && detail.document.processing_status === "ready" && detail.review_status !== "completed";
  const canVoid = detail.document.source_kind === "upload" && !completed && detail.document.processing_status !== "voided";
  const canRetry = detail.document.source_kind === "upload" && ["failed", "cancelled"].includes(detail.document.processing_status) && detail.current_revision === null;
  const reopenable = canReopen(detail);
  const selectionRequired = detail.match_status === "needs_selection";
  const selectionExpanded = showSelectionTools || selectionRequired;
  const automaticSelection = detail.selection_origin === "automatic" && selectedRevisions.length > 0;
  const hasSelection = selectedRevisions.length > 0;
  const selectedReceivingLabel = selectedRevisions
    .map((revision) => revision.payload.document_number || "编号未知")
    .join("、");
  const resultSummary = completed
    ? { title: "核对已完成", message: "正式结果和当时使用的单据快照已经保存。" }
    : detail.document.processing_status === "processing" || detail.preview_stale
      ? { title: "系统正在自动处理", message: "处理完成后会自动更新本页，无需手动开始提取或匹配。" }
      : detail.document.display_status === "waiting_counterpart"
        ? { title: "等待另一方单据", message: "单据会保留在这里；另一方到达后系统会自动关联并生成结果。" }
        : outcome === "consistent"
          ? { title: "未发现差异，等待确认", message: "请快速检查关联单据和逐行结果，然后确认一次。" }
          : outcome === "difference"
            ? { title: `发现 ${preview?.summary.different_lines ?? 0} 行差异`, message: "请查看差异；可以先标记待核实，或填写处理说明后完成。" }
            : outcome === "blocked"
              ? { title: "存在需要修正的问题", message: "请先修正阻断字段或关联关系，再确认结果。" }
              : { title: displayStatusLabel(detail.document.display_status), message: "系统会根据当前单据状态继续处理。" };

  return (
    <section className="page workspace-detail-page">
      <div className="workspace-detail-toolbar">
        <button className="back-link" onClick={() => onNavigate("/")}>← 返回工作台</button>
        <button onClick={() => void refresh(false)}>刷新详情</button>
      </div>
      <div className="review-heading workspace-detail-heading">
        <div>
          <span className="eyebrow">{isInvoice ? "发票" : "收货单"} · 修订 {detail.document.revision}</span>
          <h2>{detail.document.document_number || "尚未提取编号"}</h2>
          <p>{detail.document.supplier_name || "尚未提取供应商"}</p>
        </div>
        <div className="workspace-state-stack">
          <span className={`status ${detail.document.display_status}`}>{displayStatusLabel(detail.document.display_status)}</span>
          <small>{detail.document.source_kind === "taptouch" ? "上游权威记录，只读" : "上传单据"}</small>
        </div>
      </div>

      {detail.document.source_changed && (
        <div className="runtime-banner offline"><strong>来源已更新</strong><span>已完成结果仍按历史快照保留。如需纠正，请填写原因后重开。</span></div>
      )}
      {detail.preview_stale && <div className="info-banner">字段或来源已变化，系统正在重新生成核对预览。现有预览不能确认。</div>}
      {loadError && <div className="error-banner">{loadError}</div>}
      {message && (
        <div className="error-banner">
          {message}
          {retryOperation.current && <button className="danger-link" disabled={Boolean(busy)} onClick={() => void execute(retryOperation.current!).catch(() => undefined)}>重试同一次操作</button>}
        </div>
      )}

      {isInvoice && (
        <section className={`workspace-panel result-summary-panel ${outcome ?? detail.document.display_status}`}>
          <div>
            <span className="eyebrow">当前结果</span>
            <h3>{resultSummary.title}</h3>
            <p>{resultSummary.message}</p>
            {automaticSelection && <small>已自动关联：{selectedReceivingLabel}</small>}
          </div>
          {detail.preview && mutableInvoice && !detail.preview_stale && outcome !== "blocked" && (
            <a className="primary result-summary-action" href="#confirmation-section">查看并确认</a>
          )}
        </section>
      )}

      {!isInvoice && detail.related_invoices.length > 0 && (
        <section className="workspace-panel related-invoices-panel">
          <div className="workspace-panel-heading">
            <div><span className="eyebrow">当前关系</span><h3>关联发票</h3><p>{detail.related_invoices.length === 1 ? "这张收货单已有唯一核对入口。" : "这张收货单目前关联到多张未完成发票，请人工核实。"}</p></div>
          </div>
          <div className="related-invoice-list">
            {detail.related_invoices.map((invoice) => (
              <button key={invoice.document_id} onClick={() => onNavigate(`/documents/${encodeURIComponent(invoice.document_id)}?view=compare`)}>
                <strong>{invoice.document_number || "尚未提取编号"}</strong>
                <small>{invoice.supplier_name || "尚未提取供应商"} · {displayStatusLabel(invoice.display_status)}</small>
              </button>
            ))}
          </div>
        </section>
      )}

      <div className={`workspace-source-review ${isInvoice && hasSelection ? "paired" : "single"}`}>
        <section className="workspace-panel source-document-panel">
          <div className="workspace-panel-heading"><div><span className="eyebrow">{isInvoice ? "Invoice 原件" : "Receive Note 原件"}</span><strong className="source-document-title">{detail.document.document_number || "当前单据"}</strong></div></div>
          <SourceViewer source={source} unavailableText={detail.document.source_kind === "taptouch" ? "该记录来自 TapTouch，只提供结构化只读数据。" : "该单据没有可展示的上传原件。"} />
          <div className="evidence-list">
            {detail.current_revision?.evidence.map((item, index) => (
              <article className="evidence" key={`${item.field_path}-${index}`}><strong>{item.field_path}</strong><span>{item.page ? `页码 ${item.page}` : "页码未知"}</span><p>{item.source_text}</p></article>
            ))}
          </div>
        </section>

        {isInvoice && hasSelection && (
          <section className="workspace-panel receiving-source-panel">
            <div className="workspace-panel-heading receiving-source-heading">
              <div><span className="eyebrow">Receive Note 原件</span><strong className="source-document-title">{activeReceiving?.payload.document_number || "所选收货记录"}</strong></div>
              {selectedRevisions.length > 1 && (
                <div className="receiving-source-tabs" role="tablist" aria-label="所选收货单原件">
                  {selectedRevisions.map((revision) => (
                    <button aria-selected={revision.document_id === activeReceivingId} className={revision.document_id === activeReceivingId ? "active" : ""} key={revision.document_id} onClick={() => setActiveReceivingId(revision.document_id)} role="tab" type="button">
                      {revision.payload.document_number || "编号未知"}
                    </button>
                  ))}
                </div>
              )}
            </div>
            <SourceViewer source={receivingSource} unavailableText={activeReceiving ? "该收货记录来自 TapTouch，只提供结构化只读数据。" : "尚未选择收货记录。"} />
            {activeReceiving && <div className="source-quick-summary"><span>{activeReceiving.payload.items.length} 个商品行</span><span>{activeReceiving.evidence.length} 条原文证据</span></div>}
          </section>
        )}

        <details className="workspace-panel document-editor-panel" onToggle={(event) => setShowStructuredFields(event.currentTarget.open)} open={showStructuredFields || !hasSelection}>
          <summary className="workspace-panel-heading">
            <div><span className="eyebrow">结构化数据</span><h3>提取字段</h3></div>
            {!editable && <span className="read-only-pill">只读</span>}
          </summary>
          {detail.current_revision ? (
            <StructuredDocumentEditor
              editor={editor}
              evidence={detail.current_revision.evidence}
              issues={detail.current_revision.validation_issues}
              onChange={(value) => { setEditor(value); setEditorDirty(true); editorDirtyRef.current = true; }}
              readOnly={!editable}
              allowAdvancedJson={allowAdvancedJson}
            />
          ) : <div className="empty-state">结构化数据尚未就绪。</div>}
          {editable && (
            <div className="workspace-save-row">
              <label>修改原因<input list="edit-reason-options" maxLength={2000} onChange={(event) => setEditReason(event.target.value)} placeholder="选择常用原因或直接输入" value={editReason} /></label>
              <datalist id="edit-reason-options"><option value="提取内容与原件不一致" /><option value="补充原件中的缺失字段" /><option value="修正商品或数量信息" /></datalist>
              <button
                disabled={!editorDirty || !editReason.trim() || Boolean(busy)}
                onClick={() => {
                  let document: DocumentPayload;
                  try { document = JSON.parse(editor) as DocumentPayload; }
                  catch { setMessage("结构化数据不是有效 JSON"); return; }
                  const body = { expected_revision: detail.document.revision, document, reason: editReason.trim() };
                  startOperation("保存字段", async (key) => {
                    await editDocument(documentId, body, { idempotencyKey: key });
                    await refresh(true);
                    setMessage("字段已保存，系统正在重新核对。");
                  });
                }}
              >显式保存字段</button>
            </div>
          )}
        </details>
      </div>

      {mutableInvoice && (
        <section className="workspace-panel receiving-selection-panel">
          <div className="workspace-panel-heading">
            <div>
              <span className="eyebrow">关联</span>
              <h3>{automaticSelection ? `已自动关联 ${selectedRevisions.length} 张收货单` : hasSelection ? `已选择 ${selectedRevisions.length} 张收货单` : selectionRequired ? "需要选择收货记录" : "关联收货记录"}</h3>
              <p>{hasSelection ? `${selectedReceivingLabel}。${automaticSelection ? "系统已生成核对预览；只有关联不正确时才需要修改。" : "这是人工保存的关联，可按需修改。"}` : "系统没有找到唯一关系，请选择实际对应的收货记录。"}</p>
            </div>
            {!selectionRequired && <button type="button" onClick={() => setShowSelectionTools((value) => !value)}>
              {selectionExpanded ? "收起选择" : hasSelection ? "修改关联" : "选择收货记录"}
            </button>}
          </div>
          {selectionExpanded && (
            <div className="selection-tools">
              <p className="selection-guidance">规则分只用于候选排序，不是匹配概率。人工选择不会随新记录到达而自动扩充。</p>
              <div className="candidate-grid">
                {detail.candidates.map((candidate) => {
                  const disabled = candidateDisabled(candidate);
                  return (
                    <label className={`workspace-candidate ${disabled ? "disabled" : ""}`} key={candidate.document_id}>
                      <input
                        aria-label={`选择收货记录 ${candidate.document_number}`}
                        checked={selectedIds.includes(candidate.document_id)}
                        disabled={disabled}
                        onChange={(event) => {
                          setSelectedIds((current) => event.target.checked ? [...new Set([...current, candidate.document_id])] : current.filter((id) => id !== candidate.document_id));
                          setSelectionDirty(true);
                          selectionDirtyRef.current = true;
                        }}
                        type="checkbox"
                      />
                      <span><strong>{candidate.document_number}</strong><small>{candidate.supplier_name || "供应商未知"} · {candidate.document_date || "日期未知"}</small><small>{candidate.reason_codes.map(label).join("、")}</small></span>
                      <b>规则 {candidate.score}</b>
                    </label>
                  );
                })}
                {!detail.candidates.length && <div className="empty-state">当前没有自动候选。可在下方搜索同店已就绪收货记录。</div>}
              </div>
              <form className="manual-receiving-search" onSubmit={(event) => { event.preventDefault(); void searchManualReceivings(); }}>
                <label>搜索更多已就绪收货记录<input maxLength={100} onChange={(event) => setManualQuery(event.target.value)} placeholder="收货单编号或供应商" value={manualQuery} /></label>
                <button disabled={manualSearching} type="submit">{manualSearching ? "正在搜索…" : "搜索"}</button>
              </form>
              {manualResults.length > 0 && (
                <div className="candidate-grid manual-results">
                  {manualResults.map((result) => (
                    <label className={`workspace-candidate ${result.eligible ? "" : "disabled"}`} key={result.summary.document_id}>
                      <input
                        aria-label={`选择收货记录 ${result.summary.document_number || "编号未知"}`}
                        checked={selectedIds.includes(result.summary.document_id)}
                        disabled={!result.eligible}
                        onChange={(event) => {
                          setSelectedIds((current) => event.target.checked ? [...new Set([...current, result.summary.document_id])] : current.filter((id) => id !== result.summary.document_id));
                          setSelectionDirty(true);
                          selectionDirtyRef.current = true;
                        }}
                        type="checkbox"
                      />
                      <span><strong>{result.summary.document_number || "编号未知"}</strong><small>{result.summary.supplier_name || "供应商未知"} · {result.summary.document_date || "日期未知"}</small><small>{result.reason}</small></span>
                    </label>
                  ))}
                </div>
              )}
              <div className="workspace-save-row">
                <label>人工选择原因<input list="selection-reason-options" maxLength={2000} onChange={(event) => setSelectionReason(event.target.value)} placeholder="选择常用原因或直接输入" value={selectionReason} /></label>
                <datalist id="selection-reason-options"><option value="系统关联的收货记录不正确" /><option value="根据原件确认对应收货记录" /><option value="补充较早或较晚到达的收货记录" /></datalist>
                <button
                  disabled={!selectionDirty || !selectionReason.trim() || Boolean(busy)}
                  onClick={() => {
                    const body = { expected_revision: detail.document.revision, receive_document_ids: [...selectedIds], reason: selectionReason.trim() };
                    startOperation("保存关联", async (key) => {
                      await selectReceivings(documentId, body, { idempotencyKey: key });
                      await refresh(true);
                      setShowSelectionTools(false);
                      setMessage(selectedIds.length ? "人工关联已保存，系统正在重新核对。" : "已恢复自动选择模式。");
                    });
                  }}
                >{selectedIds.length ? "保存所选收货记录" : "清除人工选择并恢复自动"}</button>
              </div>
            </div>
          )}
        </section>
      )}

      {isInvoice && detail.preview && (
        <section className="workspace-panel preview-panel">
          <div className="workspace-panel-heading preview-heading"><div><span className="eyebrow">核对预览</span><h3>{label(detail.preview.result.outcome)}</h3><p>{label(detail.preview.result.coverage)} · {unverifiedSummary(detail.preview.result)}</p></div><span className={`result-decision ${outcome === "consistent" ? "clear" : "review"}`}>{label(outcome ?? "")}</span></div>
          {preview?.blocking_codes.length ? <div className="error-banner">阻断：{preview.blocking_codes.map(label).join("、")}</div> : null}
          <div className="workspace-metrics"><div><strong>{preview?.summary.total_lines}</strong><span>商品行</span></div><div><strong>{preview?.summary.different_lines}</strong><span>差异行</span></div><div><strong>{preview?.summary.unverified_lines}</strong><span>未核验行</span></div></div>
          <div className="table-scroll"><table className="result-table"><thead><tr><th>商品</th><th>数量</th><th>单价</th><th>金额</th><th>行状态</th></tr></thead><tbody>{preview?.lines.map((line) => <tr key={line.match_key}><td><button className="line-source-button" disabled={!line.receive_lines.length} onClick={() => { const sourceId = line.receive_lines[0]?.document_id; if (sourceId) setActiveReceivingId(sourceId); }} title={line.receive_lines.length ? "查看对应收货单原件" : "该行没有对应收货记录"} type="button"><strong>{line.sku || line.description}</strong>{line.sku && <small>{line.description}</small>}</button></td><td>{line.quantity.invoice_value ?? "—"} / {line.quantity.received_value ?? "—"}<small>{metricStatusLabel(line.quantity.status)}</small></td><td>{line.price.invoice_value ?? "—"} / {line.price.received_value ?? "—"}<small>{metricStatusLabel(line.price.status)}</small></td><td>{line.amount.invoice_value ?? "—"} / {line.amount.received_value ?? "—"}<small>{metricStatusLabel(line.amount.status)}</small></td><td>{label(line.status)}</td></tr>)}</tbody></table></div>
        </section>
      )}

      {mutableInvoice && (
        <section className="workspace-panel decision-panel" id="confirmation-section">
          <div className="workspace-panel-heading"><div><span className="eyebrow">一次人工确认</span><h3>确认核对结果</h3><p>确认前请核对上传字段、所选收货记录、证据和全部未核验项目。</p></div></div>
          <div className="confirmation-sources">
            {detail.current_revision && <article><h4>发票字段</h4><dl>{payloadSummary(detail.current_revision.payload).map(([name, value]) => <div key={name}><dt>{name}</dt><dd>{value}</dd></div>)}</dl><p>{detail.current_revision.payload.items.length} 个商品行</p></article>}
            {selectedRevisions.map((revision) => <article key={revision.document_id}><h4>所选收货记录</h4><dl>{payloadSummary(revision.payload).map(([name, value]) => <div key={name}><dt>{name}</dt><dd>{value}</dd></div>)}</dl><p>{revision.payload.items.length} 个商品行 · {revision.evidence.length} 条证据</p></article>)}
          </div>
          {preview?.unverified_dimensions.length ? <div className="unverified-list"><strong>未核验维度</strong><ul>{preview.unverified_dimensions.map((dimension) => <li key={dimension}>{label(dimension)}</li>)}</ul></div> : null}
          {outcome === "difference" && <label>差异处理说明<textarea maxLength={2000} onChange={(event) => setResolutionNote(event.target.value)} placeholder="说明如何处理；原差异仍会保留在正式快照中" rows={3} value={resolutionNote} /></label>}
          <label className="confirmation-check"><input checked={acknowledged} onChange={(event) => setAcknowledged(event.target.checked)} type="checkbox" />我已核对发票、所选收货记录与未核验项目</label>
          {(editorDirty || selectionDirty) && <div className="info-banner">存在未保存的字段或关联选择。请先显式保存并等待新预览。</div>}
          {outcome === "blocked" && <div className="error-banner">当前预览存在阻断项，不能确认。请先修正字段或关联。</div>}
          <div className="decision-actions">
            <label>待核实备注<input maxLength={2000} onChange={(event) => setInvestigateNote(event.target.value)} placeholder="等待补货或联系供应商时填写" value={investigateNote} /></label>
            <button
              disabled={!investigateNote.trim() || Boolean(busy)}
              onClick={() => {
                const body = { expected_revision: detail.document.revision, note: investigateNote.trim() };
                startOperation("保存待核实", async (key) => { await investigate(documentId, body, { idempotencyKey: key }); await refresh(false); setInvestigateNote(""); setMessage("已保存为待核实，尚未完成核对。"); });
              }}
            >保存待核实</button>
            <button
              className="primary confirm-button"
              disabled={!confirmable || !acknowledged || (outcome === "difference" && !resolutionNote.trim()) || Boolean(busy)}
              onClick={() => {
                if (!detail.preview || !preview) return;
                const body = {
                  expected_revision: detail.document.revision,
                  preview_id: detail.preview.preview_id,
                  acknowledged_sources: true as const,
                  acknowledged_unverified_dimensions: [...preview.unverified_dimensions],
                  resolution: outcome === "difference" ? "resolved_with_note" as const : "matched" as const,
                  note: outcome === "difference" ? resolutionNote.trim() : null,
                };
                startOperation("确认核对结果", async (key) => { await confirm(documentId, body, { idempotencyKey: key }); await refresh(true); setAcknowledged(false); setResolutionNote(""); setMessage(outcome === "difference" ? "已按说明完成；原差异保留在正式结果中。" : "核对结果已确认。"); });
              }}
            >确认核对结果</button>
          </div>
        </section>
      )}

      {detail.confirmation && (
        <section className="workspace-panel historical-result-panel">
          <div className="workspace-panel-heading"><div><span className="eyebrow">正式历史快照</span><h3>{label(detail.confirmation.resolution)}</h3><p>{new Date(detail.confirmation.created_at).toLocaleString()} · {detail.confirmation.receive_note_numbers.join("、") || "无收货单"}</p></div><button onClick={() => void exportConfirmation(detail.confirmation!.confirmation_id)}>导出 CSV</button></div>
          {detail.confirmation.note && <p className="historical-note">{detail.confirmation.note}</p>}
          <p>{label(detail.confirmation.result_snapshot.outcome)} · {unverifiedSummary(detail.confirmation.result_snapshot)}</p>
        </section>
      )}

      {(reopenable || canVoid || canRetry) && <section className="workspace-panel document-maintenance-panel">
        {reopenable && <div className="maintenance-action"><label>重开原因<input maxLength={2000} onChange={(event) => setReopenReason(event.target.value)} value={reopenReason} /></label><button disabled={!reopenReason.trim() || Boolean(busy)} onClick={() => { const body = { expected_revision: detail.document.revision, reason: reopenReason.trim() }; startOperation("重开", async (key) => { await reopen(documentId, body, { idempotencyKey: key }); await refresh(true); setReopenReason(""); setMessage("已重开；历史结果保持不变，收货占用已释放。"); }); }}>重开核对</button></div>}
        {canVoid && <div className="maintenance-action"><label>作废原因<input maxLength={2000} onChange={(event) => setVoidReason(event.target.value)} value={voidReason} /></label><button className="danger" disabled={!voidReason.trim() || Boolean(busy)} onClick={() => { const body = { expected_revision: detail.document.revision, reason: voidReason.trim() }; startOperation("作废", async (key) => { await voidDocument(documentId, body, { idempotencyKey: key }); await refresh(true); setVoidReason(""); setMessage("单据已作废。"); }); }}>作废单据</button></div>}
        {canRetry && <button disabled={Boolean(busy)} onClick={() => { const body = { expected_revision: detail.document.revision }; startOperation("重试处理", async (key) => { await retry(documentId, body, { idempotencyKey: key }); await refresh(false); setMessage("已请求重试，后台将继续处理。"); }); }}>重试自动处理</button>}
      </section>}

      <section className="workspace-panel audit-panel">
        <div className="workspace-panel-heading"><div><span className="eyebrow">审计</span><h3>操作记录</h3><p>详情显示最新 50 条，可继续读取更早记录。</p></div></div>
        <ol className="workspace-actions">{allActions.map((action) => <li key={action.action_id}><div><strong>{label(action.action)}</strong><time dateTime={action.created_at}>{new Date(action.created_at).toLocaleString()}</time></div><p>{action.reason ?? "无备注"}</p><small>{action.actor_id ?? "系统"} · 修订 {action.new_revision}</small></li>)}</ol>
        {detail.actions.length >= 50 && (actionsTotal === null || allActions.length < actionsTotal) && <button onClick={() => void loadOlderActions()}>查看更早记录</button>}
      </section>
    </section>
  );
}
