import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";

/**
 * 对账页分成两个不同决策：
 *
 * 1. Candidate Matching 回答“哪些收货单可能属于这张发票”，只做可解释排序；
 * 2. Reconciliation 回答“选定单据的数量/金额是否一致”，产生可审计记录。
 *
 * 候选算法不会自动替用户确认关系，且两个步骤都只接收人工批准的不可变版本。
 */
type ApprovedVersion = {
  version_id: string;
  document_type: "invoice" | "receive_note";
  version_number: number;
  document_json: {
    document_number?: string;
    purchase_order_number?: string;
    supplier?: { name?: string };
  };
  approved_at: string;
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
  score: number;
  confidence: "high" | "medium" | "low";
  recommended: boolean;
  signals: CandidateSignal[];
};

export function ReconciliationPage() {
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
      setError(problem instanceof Error ? problem.message : "Comparison failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="page">
      <div className="page-heading">
        <div>
          <span className="eyebrow">THREE-WAY CONTROL</span>
          <h2>Invoice and Receive Note reconciliation</h2>
          <p>Only immutable, human-approved versions are available here.</p>
        </div>
      </div>

      <div className="reconcile-picker">
        <div>
          <label htmlFor="invoice-version">Approved Invoice</label>
          <select
            id="invoice-version"
            value={invoiceId}
            onChange={(event) => {
              setInvoiceId(event.target.value);
              setNoteIds([]);
              setResult(null);
              setError("");
            }}
          >
            <option value="">Select an invoice</option>
            {invoices.map((version) => (
              <option key={version.version_id} value={version.version_id}>
                {version.document_json.document_number || "Unnamed invoice"} · v
                {version.version_number}
              </option>
            ))}
          </select>
        </div>
        <fieldset>
          <legend>Suggested Receive Notes</legend>
          <p className="candidate-guidance">
            Suggestions are ranked by PO, supplier, location, currency, date,
            and item overlap. A reviewer must still confirm the selection.
          </p>
          <div className="note-options">
            {!invoiceId && (
              <div className="empty-inline">
                Select an Invoice to calculate matching candidates.
              </div>
            )}
            {invoiceId && candidates.isLoading && (
              <div className="empty-inline">Scoring approved Receive Notes…</div>
            )}
            {candidates.data?.map((candidate) => (
              <label
                className={`check-option candidate-option ${candidate.confidence}`}
                key={candidate.receive_note_version_id}
              >
                <input
                  type="checkbox"
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
                    {candidate.recommended && (
                      <b className="recommended-badge">Recommended</b>
                    )}
                    <b className={`score-badge ${candidate.confidence}`}>
                      {candidate.score}/100
                    </b>
                  </span>
                  <small>
                    {candidate.purchase_order_number || "No PO"} ·{" "}
                    {candidate.supplier_name || "Unknown supplier"} ·{" "}
                    {candidate.document_date || "No date"}
                  </small>
                  <details
                    className="candidate-signals"
                    onClick={(event) => event.stopPropagation()}
                  >
                    <summary>Why this score</summary>
                    <ul>
                      {candidate.signals.map((signal) => (
                        <li className={signal.outcome} key={signal.code}>
                          <span>{signal.message}</span>
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
              <div className="empty-inline">No approved Receive Notes.</div>
            )}
            {candidates.isError && (
              <div className="error-banner">
                {candidates.error instanceof Error
                  ? candidates.error.message
                  : "Could not calculate candidates"}
              </div>
            )}
          </div>
        </fieldset>
        <button
          className="primary compare-button"
          disabled={!invoiceId || !noteIds.length || busy}
          onClick={compare}
        >
          {busy ? "Comparing…" : "Run reconciliation"}
        </button>
      </div>

      {error && <div className="error-banner">{error}</div>}
      {!versions.isLoading && (!invoices.length || !receiveNotes.length) && (
        <div className="info-banner">
          Approve at least one Invoice and one Receive Note before reconciling.
        </div>
      )}

      {result && (
        <div className="reconciliation-result">
          <div className="result-heading">
            <div>
              <span className="eyebrow">RESULT</span>
              <h3>{result.result.invoice_number}</h3>
              <p>Against {result.result.receive_note_numbers.join(", ")}</p>
            </div>
            <span
              className={`result-decision ${
                result.result.summary.requires_review ? "review" : "clear"
              }`}
            >
              {result.result.summary.requires_review
                ? "Review required"
                : "Matched"}
            </span>
          </div>
          <div className="metric-strip">
            <div><strong>{result.result.summary.total_lines}</strong><span>Lines</span></div>
            <div><strong>{result.result.summary.exact_lines}</strong><span>Exact</span></div>
            <div><strong>{result.result.summary.tolerance_lines}</strong><span>Tolerance</span></div>
            <div><strong>{result.result.summary.mismatch_lines}</strong><span>Mismatch</span></div>
          </div>
          <div className="table-scroll">
            <table className="result-table">
              <thead>
                <tr>
                  <th>Item</th>
                  <th>Invoice qty</th>
                  <th>Received qty</th>
                  <th>Difference</th>
                  <th>Status</th>
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
                        {line.status.replaceAll("_", " ")}
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
