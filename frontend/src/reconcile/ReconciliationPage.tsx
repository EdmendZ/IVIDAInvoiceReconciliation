import { label, systemMessage } from "../i18n";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, downloadFile } from "../api/client";

/**
 * 对账页分成两个不同决策：
 *
 * 1. Candidate Matching 回答“哪些收货单可能属于这张发票”，只做可解释排序；
 * 2. Reconciliation 回答“选定单据的数量/金额是否一致”，产生可审计记录。
 *
 * 候选算法不会自动替用户确认关系，且两个步骤都只接收可信的不可变版本。
 */
type ApprovedVersion = {
  version_id: string;
  document_type: "invoice" | "receive_note";
  version_number: number | null;
  document_json: {
    document_number?: string;
    purchase_order_number?: string;
    supplier?: { name?: string };
  };
  approved_at: string | null;
  source_kind: "invoice_upload" | "external_receive_note_upload" | "taptouch_receiving";
  trust_method: "human_approved" | "upstream_authoritative";
};

type LineResult = {
  match_key: string;
  sku: string | null;
  description: string;
  invoice_quantity: string;
  received_quantity: string;
  quantity_difference: string;
  invoice_amount: string | null;
  received_amount: string | null;
  amount_difference: string | null;
  status: string;
  reasons: string[];
};

type ReconciliationRecord = {
  reconciliation_id: string;
  result: {
    invoice_number: string;
    receive_note_numbers: string[];
    purchase_order_match: boolean | null;
    currency_match: boolean;
    summary: {
      total_lines: number;
      exact_lines: number;
      tolerance_lines: number;
      mismatch_lines: number;
      invoice_only_lines: number;
      receive_note_only_lines: number;
      requires_review: boolean;
    };
    lines: LineResult[];
  };
};

type CandidateSignal = {
  code: string;
  outcome: "match" | "conflict" | "unknown";
  message: string;
  weight: number;
};

type ReconciliationCandidate = {
  receive_note_version_id: string;
  document_number: string;
  purchase_order_number: string | null;
  supplier_name: string | null;
  document_date: string | null;
  source_kind: ApprovedVersion["source_kind"];
  trust_method: ApprovedVersion["trust_method"];
  external_store_id: string | null;
  external_receiving_id: string | null;
  external_version: number | null;
  upstream_updated_at: string | null;
  score: number;
  confidence: "high" | "medium" | "low";
  recommended: boolean;
  signals: CandidateSignal[];
};

const sourceLabels: Record<ApprovedVersion["source_kind"], string> = {
  invoice_upload: "上传的发票",
  external_receive_note_upload: "上传的收货单",
  taptouch_receiving: "TapTouch 收货记录",
};

export function ReconciliationPage({ readOnly = false }: { readOnly?: boolean }) {
  const versions = useQuery({
    queryKey: ["approved-versions"],
    queryFn: () =>
      api<ApprovedVersion[]>("/api/review/approved-versions"),
  });
  const [invoiceId, setInvoiceId] = useState("");
  const [noteIds, setNoteIds] = useState<string[]>([]);
  const [result, setResult] = useState<ReconciliationRecord | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const candidates = useQuery({
    queryKey: ["reconciliation-candidates", invoiceId],
    queryFn: () =>
      api<ReconciliationCandidate[]>(
        `/api/reconciliations/candidates?invoice_version_id=${encodeURIComponent(invoiceId)}`,
      ),
    enabled: Boolean(invoiceId),
  });

  const invoices = useMemo(
    () => versions.data?.filter((item) => item.document_type === "invoice") ?? [],
    [versions.data],
  );
  const receiveNotes = useMemo(
    () =>
      versions.data?.filter((item) => item.document_type === "receive_note") ?? [],
    [versions.data],
  );

  async function compare() {
    setBusy(true);
    setError("");
    setResult(null);
    try {
      // 后端再次校验版本类型和 approved 状态，前端下拉框过滤不是安全边界。
      const record = await api<ReconciliationRecord>("/api/reconciliations", {
        method: "POST",
        body: JSON.stringify({
          invoice_version_id: invoiceId,
          receive_note_version_ids: noteIds,
        }),
      });
      setResult(record);
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : "对账失败");
    } finally {
      setBusy(false);
    }
  }

  async function exportCsv() {
    if (!result) return;
    setError("");
    try {
      await downloadFile(
        `/api/reconciliations/${encodeURIComponent(result.reconciliation_id)}/export.csv`,
      );
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : "导出失败");
    }
  }

  return (
    <section className="page">
      <div className="page-heading">
        <div>
          <span className="eyebrow">收货对账</span>
          <h2>发票与收货单核对</h2>
          <p>仅可选择已确认且不可变更的可信单据版本。</p>
        </div>
      </div>

      <div className="reconcile-picker">
        <div>
          <label htmlFor="invoice-version">已批准的发票</label>
          <select
            id="invoice-version"
            disabled={readOnly}
            value={invoiceId}
            onChange={(event) => {
              setInvoiceId(event.target.value);
              setNoteIds([]);
              setResult(null);
              setError("");
            }}
          >
            <option value="">选择发票</option>
            {invoices.map((version) => (
              <option key={version.version_id} value={version.version_id}>
                {version.document_json.document_number || "未命名发票"} · v
                {version.version_number}
              </option>
            ))}
          </select>
        </div>
        <fieldset>
          <legend>候选收货单</legend>
          <p className="candidate-guidance">
            根据订单号、供应商、地点、币种、日期和商品重合度排序，请人工确认所选收货单。
          </p>
          <div className="note-options">
            {!invoiceId && (
              <div className="empty-inline">
                请先选择发票以查找候选收货单。
              </div>
            )}
            {invoiceId && candidates.isLoading && (
              <div className="empty-inline">正在评估候选收货单…</div>
            )}
            {candidates.data?.map((candidate) => (
              <label
                className={`check-option candidate-option ${candidate.confidence}`}
                key={candidate.receive_note_version_id}
              >
                <input
                  type="checkbox"
                  disabled={readOnly}
                  checked={noteIds.includes(candidate.receive_note_version_id)}
                  onChange={(event) =>
                    setNoteIds((current) =>
                      event.target.checked
                        ? [...current, candidate.receive_note_version_id]
                        : current.filter(
                            (id) => id !== candidate.receive_note_version_id,
                          ),
                    )
                  }
                />
                <span className="candidate-main">
                  <span className="candidate-title">
                    <strong>{candidate.document_number}</strong>
                    <b className={`source-badge ${candidate.source_kind}`}>
                      {sourceLabels[candidate.source_kind]}
                    </b>
                    {candidate.recommended && (
                      <b className="recommended-badge">推荐</b>
                    )}
                    <b className={`score-badge ${candidate.confidence}`}>
                      {candidate.score}/100
                    </b>
                  </span>
                  <small>
                    {candidate.purchase_order_number || "无订单号"} ·{" "}
                    {candidate.supplier_name || "未知供应商"} ·{" "}
                    {candidate.document_date || "无日期"}
                  </small>
                  {candidate.source_kind === "taptouch_receiving" && (
                    <small className="source-context">
                      门店 {candidate.external_store_id} · 收货记录 {candidate.external_receiving_id} · 上游版本{candidate.external_version}
                      {candidate.upstream_updated_at
                        ? ` · 更新时间 ${new Date(candidate.upstream_updated_at).toLocaleString()}`
                        : ""}
                    </small>
                  )}
                  <details
                    className="candidate-signals"
                    onClick={(event) => event.stopPropagation()}
                  >
                    <summary>评分依据</summary>
                    <ul>
                      {candidate.signals.map((signal) => (
                        <li className={signal.outcome} key={signal.code}>
                          <span>{systemMessage(signal.message)}</span>
                          <b>{signal.weight > 0 ? `+${signal.weight}` : signal.weight}</b>
                        </li>
                      ))}
                    </ul>
                  </details>
                </span>
              </label>
            ))}
            {invoiceId &&
              !candidates.isLoading &&
              !candidates.data?.length &&
              !candidates.isError && (
              <div className="empty-inline">没有可用的已批准收货单。</div>
            )}
            {candidates.isError && (
              <div className="error-banner">
                {candidates.error instanceof Error
                  ? candidates.error.message
                  : "无法计算候选匹配"}
              </div>
            )}
          </div>
        </fieldset>
        {!readOnly && <button
          className="primary compare-button"
          disabled={!invoiceId || !noteIds.length || busy}
          onClick={compare}
        >
          {busy ? "正在核对…" : "开始核对"}
        </button>}
      </div>

      {error && <div className="error-banner">{error}</div>}
      {!versions.isLoading && (!invoices.length || !receiveNotes.length) && (
        <div className="info-banner">
          请先批准至少一张发票和一张收货单。
        </div>
      )}

      {result && (
        <div className="reconciliation-result">
          <div className="result-heading">
            <div>
              <span className="eyebrow">核对结果</span>
              <h3>{result.result.invoice_number}</h3>
              <p>对应收货单 {result.result.receive_note_numbers.join(", ")}</p>
            </div>
            <span
              className={`result-decision ${
                result.result.summary.requires_review ? "review" : "clear"
              }`}
            >
              {result.result.summary.requires_review
                ? "需要复核"
                : "已匹配"}
            </span>
            <button onClick={exportCsv}>导出 CSV</button>
          </div>
          <div className="metric-strip">
            <div><strong>{result.result.summary.total_lines}</strong><span>行数</span></div>
            <div><strong>{result.result.summary.exact_lines}</strong><span>完全匹配</span></div>
            <div><strong>{result.result.summary.tolerance_lines}</strong><span>容差内</span></div>
            <div><strong>{result.result.summary.mismatch_lines}</strong><span>不匹配</span></div>
          </div>
          <div className="table-scroll">
            <table className="result-table">
              <thead>
                <tr>
                  <th>商品</th>
                  <th>发票数量</th>
                  <th>收货数量</th>
                  <th>差异</th>
                  <th>状态</th>
                </tr>
              </thead>
              <tbody>
                {result.result.lines.map((line) => (
                  <tr key={line.match_key}>
                    <td>
                      <strong>{line.sku || line.description}</strong>
                      {line.sku && <small>{line.description}</small>}
                    </td>
                    <td>{line.invoice_quantity}</td>
                    <td>{line.received_quantity}</td>
                    <td>{line.quantity_difference}</td>
                    <td>
                      <span className={`status ${line.status}`}>
                        {label(line.status)}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  );
}
