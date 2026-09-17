import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { label } from "../i18n";
import { exportConfirmation, getConfirmation, listConfirmations } from "../workspace/workspaceClient";
import type { PreviewOutcome } from "../workspace/workspaceTypes";
import { metricStatusLabel, unverifiedSummary } from "../workspace/workspacePresentation";

type HistoryPageProps = {
  confirmationId?: string;
  onNavigate: (path: string) => void;
};

function SnapshotDetail({ confirmationId, onNavigate }: Required<HistoryPageProps>) {
  const detail = useQuery({
    queryKey: ["workspace-confirmation", confirmationId],
    queryFn: () => getConfirmation(confirmationId),
  });

  if (detail.isLoading) return <section className="page"><div className="empty-state">正在加载正式核对快照…</div></section>;
  if (detail.error || !detail.data) {
    return <section className="page"><div className="error-banner">{detail.error instanceof Error ? detail.error.message : "无法读取正式核对快照"}</div><button onClick={() => onNavigate("/history")}>返回历史记录</button></section>;
  }

  const confirmation = detail.data;
  const result = confirmation.result_snapshot;
  return (
    <section className="page history-page">
      <div className="page-heading">
        <div><span className="eyebrow">不可变正式快照</span><h2>{confirmation.invoice_number}</h2><p>{confirmation.receive_note_numbers.join("、") || "无收货单编号"}</p></div>
        <div className="history-heading-actions"><button onClick={() => onNavigate("/history")}>返回历史记录</button><button className="primary" onClick={() => void exportConfirmation(confirmation.confirmation_id)}>导出 CSV</button></div>
      </div>

      <section className="workspace-panel history-snapshot-summary">
        <div><span>确认结果</span><strong>{label(confirmation.resolution)}</strong></div>
        <div><span>核对结论</span><strong>{label(result.outcome)}</strong></div>
        <div><span>核验范围</span><strong>{label(result.coverage)}</strong></div>
        <div><span>确认时间</span><strong>{new Date(confirmation.created_at).toLocaleString()}</strong></div>
        <div><span>操作人</span><strong>{confirmation.actor_id}</strong></div>
      </section>

      {confirmation.note && <section className="workspace-panel"><span className="eyebrow">处理说明</span><p className="historical-note">{confirmation.note}</p></section>}

      <section className="workspace-panel">
        <div className="workspace-panel-heading"><div><span className="eyebrow">当时保存的结果</span><h3>{label(result.outcome)}</h3><p>{unverifiedSummary(result)}</p></div></div>
        <div className="unverified-list"><strong>已确认的未核验维度</strong><ul>{confirmation.acknowledged_unverified_dimensions.map((dimension) => <li key={dimension}>{label(dimension)}</li>)}</ul></div>
        <div className="workspace-metrics"><div><strong>{result.summary.total_lines}</strong><span>商品行</span></div><div><strong>{result.summary.different_lines}</strong><span>差异行</span></div><div><strong>{result.summary.unverified_lines}</strong><span>未核验行</span></div></div>
        <div className="table-scroll"><table className="result-table"><thead><tr><th>商品</th><th>数量</th><th>单价</th><th>金额</th><th>行状态</th></tr></thead><tbody>{result.lines.map((line) => <tr key={line.match_key}><td><strong>{line.sku || line.description}</strong>{line.sku && <small>{line.description}</small>}</td><td>{line.quantity.invoice_value ?? "—"} / {line.quantity.received_value ?? "—"}<small>{metricStatusLabel(line.quantity.status)}</small></td><td>{line.price.invoice_value ?? "—"} / {line.price.received_value ?? "—"}<small>{metricStatusLabel(line.price.status)}</small></td><td>{line.amount.invoice_value ?? "—"} / {line.amount.received_value ?? "—"}<small>{metricStatusLabel(line.amount.status)}</small></td><td>{label(line.status)}</td></tr>)}</tbody></table></div>
      </section>
    </section>
  );
}

export function HistoryPage({ confirmationId, onNavigate }: HistoryPageProps) {
  const [draft, setDraft] = useState("");
  const [query, setQuery] = useState("");
  const [outcome, setOutcome] = useState<PreviewOutcome | "">("");
  const [page, setPage] = useState(1);

  const history = useQuery({
    queryKey: ["workspace-confirmations", query, outcome, page],
    queryFn: () => listConfirmations({ q: query || null, outcome: outcome ? [outcome] : [], page, page_size: 20 }),
    enabled: confirmationId === undefined,
  });

  if (confirmationId) return <SnapshotDetail confirmationId={confirmationId} onNavigate={onNavigate} />;

  const totalPages = history.data ? Math.max(1, Math.ceil(history.data.total / history.data.page_size)) : 1;
  return (
    <section className="page history-page">
      <div className="page-heading">
        <div><span className="eyebrow">正式核对结果</span><h2>核对历史</h2><p>这里显示新工作台保存的全部不可变结果，包括重开前的旧快照。</p></div>
        <button onClick={() => onNavigate("/history/legacy")}>查看旧版历史</button>
      </div>

      <form className="history-toolbar" onSubmit={(event) => { event.preventDefault(); setQuery(draft.trim()); setPage(1); }}>
        <label>搜索历史<input maxLength={100} onChange={(event) => setDraft(event.target.value)} placeholder="发票号、供应商或收货单号" value={draft} /></label>
        <label>核对结论<select onChange={(event) => { setOutcome(event.target.value as PreviewOutcome | ""); setPage(1); }} value={outcome}><option value="">全部结果</option><option value="consistent">商品明细一致</option><option value="difference">存在差异</option></select></label>
        <button type="submit">搜索</button>
        {(query || outcome) && <button type="button" onClick={() => { setDraft(""); setQuery(""); setOutcome(""); setPage(1); }}>清除筛选</button>}
      </form>

      {history.isLoading && <div className="empty-state">正在加载核对历史…</div>}
      {history.error && <div className="error-banner">{history.error instanceof Error ? history.error.message : "无法加载核对历史"}</div>}
      <div className="history-grid">
        {history.data?.items.map((item) => <article className="history-card" key={item.confirmation_id}>
          <div className="history-card-heading"><span className={`result-decision ${item.outcome === "consistent" ? "clear" : "review"}`}>{label(item.outcome)}</span><time dateTime={item.created_at}>{new Date(item.created_at).toLocaleString()}</time></div>
          <div><h3>{item.invoice_number}</h3><p>{item.supplier_name || "供应商未知"}</p><p>收货单：{item.receive_note_numbers.join("、") || "无"}</p></div>
          <div className="history-card-meta"><span>{label(item.coverage)}</span><span>{item.acknowledged_unverified_dimensions.length} 个未核验维度</span></div>
          {item.note && <p className="history-card-note">{item.note}</p>}
          <button onClick={() => onNavigate(`/history/${encodeURIComponent(item.confirmation_id)}`)}>查看正式快照</button>
        </article>)}
      </div>
      {!history.isLoading && !history.error && history.data?.items.length === 0 && <div className="empty-state">当前筛选条件下没有正式核对记录。</div>}
      {history.data && history.data.total > 0 && <div className="case-pagination" aria-label="核对历史分页"><button disabled={page === 1} onClick={() => setPage((value) => Math.max(1, value - 1))}>上一页</button><span>页码 {history.data.page} / {totalPages} · {history.data.total} 条记录</span><button disabled={page >= totalPages} onClick={() => setPage((value) => value + 1)}>下一页</button></div>}
    </section>
  );
}
