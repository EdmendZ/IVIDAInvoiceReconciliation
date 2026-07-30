import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";

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
            onChange={(event) => setInvoiceId(event.target.value)}
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
          <legend>Approved Receive Notes</legend>
          <div className="note-options">
            {receiveNotes.map((version) => (
              <label className="check-option" key={version.version_id}>
                <input
                  type="checkbox"
                  checked={noteIds.includes(version.version_id)}
                  onChange={(event) =>
                    setNoteIds((current) =>
                      event.target.checked
                        ? [...current, version.version_id]
                        : current.filter((id) => id !== version.version_id),
                    )
                  }
                />
                <span>
                  <strong>
                    {version.document_json.document_number || "Unnamed note"}
                  </strong>
                  <small>
                    {version.document_json.purchase_order_number || "No PO"} · v
                    {version.version_number}
                  </small>
                </span>
              </label>
            ))}
            {!receiveNotes.length && (
              <div className="empty-inline">No approved Receive Notes.</div>
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
