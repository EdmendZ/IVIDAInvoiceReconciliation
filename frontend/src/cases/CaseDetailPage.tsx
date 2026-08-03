import { useQuery } from "@tanstack/react-query";

import { api, type User } from "../api/client";
import {
  caseLineForItem,
  caseStatusLabel,
  resolutionLabel,
} from "./casePresentation";
import type {
  CaseActionType,
  CaseDetail,
  CaseItemType,
} from "./caseTypes";

export function CaseDetailPage({
  caseId,
  user,
  onNavigate,
}: {
  caseId: string;
  user: User;
  onNavigate: (path: string) => void;
}) {
  const detail = useQuery({
    queryKey: ["reconciliation-case", caseId],
    queryFn: () =>
      api<CaseDetail>(
        `/api/reconciliation-cases/${encodeURIComponent(caseId)}`,
      ),
  });

  if (detail.isLoading) {
    return (
      <section className="page">
        <button className="back-link" onClick={() => onNavigate("/cases")}>
          ← Back to Cases
        </button>
        <div className="empty-state">Loading case…</div>
      </section>
    );
  }

  if (detail.error || !detail.data) {
    return (
      <section className="page">
        <button className="back-link" onClick={() => onNavigate("/cases")}>
          ← Back to Cases
        </button>
        <div className="error-banner">
          {detail.error instanceof Error
            ? detail.error.message
            : "Could not load this reconciliation case"}
        </div>
      </section>
    );
  }

  const data = detail.data;
  const result = data.reconciliation.result;
  const summary = result.summary;
  const lineResults = data.line_results ?? [];
  const immutableLines = lineResults.length
    ? lineResults.map(({ line_result_id, line }) => ({
        key: line_result_id,
        line,
      }))
    : result.lines.map((line) => ({ key: line.match_key, line }));

  return (
    <section className="page case-detail-page">
      <button className="back-link" onClick={() => onNavigate("/cases")}>
        ← Back to Cases
      </button>

      <div className="case-detail-heading">
        <div>
          <span className="eyebrow">RECONCILIATION CASE</span>
          <h2>{result.invoice_number}</h2>
          <p>Against {result.receive_note_numbers.join(", ") || "no Receive Notes"}</p>
        </div>
        <div className="case-detail-state">
          <span className={`status ${data.case.status}`}>
            {caseStatusLabel(data.case.status)}
          </span>
          <small>
            Assignee:{" "}
            {data.assignee_username ||
              (data.case.assignee_user_id ? "Assigned reviewer" : "Unassigned")} ·{" "}
            Revision {data.case.revision}
          </small>
          <small>
            Viewing as {user.username} ({user.role})
          </small>
        </div>
      </div>

      <div className="case-summary-grid">
        <SummaryMetric label="Total lines" value={summary.total_lines} />
        <SummaryMetric label="Exact" value={summary.exact_lines} />
        <SummaryMetric label="Within tolerance" value={summary.tolerance_lines} />
        <SummaryMetric label="Mismatch" value={summary.mismatch_lines} />
        <SummaryMetric label="Invoice only" value={summary.invoice_only_lines} />
        <SummaryMetric
          label="Receive Note only"
          value={summary.receive_note_only_lines}
        />
      </div>

      <section className="case-section">
        <div className="case-section-heading">
          <div>
            <span className="eyebrow">ACTIONABLE DIFFERENCES</span>
            <h3>Case items</h3>
          </div>
          <span>{data.items.length} items</span>
        </div>
        <div className="case-item-list">
          {data.items.map((item) => {
            const line = caseLineForItem(item, lineResults);
            return (
              <article className="case-item" key={item.item_id}>
                <div>
                  <strong>{caseItemLabel(item.item_type)}</strong>
                  {line ? (
                    <>
                      <b>{line.sku || line.description}</b>
                      {line.sku && <small>{line.description}</small>}
                      <dl className="case-item-line-data">
                        <div>
                          <dt>Quantity diff</dt>
                          <dd>{line.quantity_difference}</dd>
                        </div>
                        <div>
                          <dt>Unit price diff</dt>
                          <dd>{line.unit_price_difference ?? "—"}</dd>
                        </div>
                        <div>
                          <dt>Amount diff</dt>
                          <dd>{line.amount_difference ?? "—"}</dd>
                        </div>
                      </dl>
                      <small>
                        {line.status.replaceAll("_", " ")}
                        {line.reasons.length ? ` · ${line.reasons.join(", ")}` : ""}
                      </small>
                    </>
                  ) : (
                    <small>{caseItemDescription(item.item_type)}</small>
                  )}
                </div>
                <div>
                  <span className="case-item-resolution">
                    {item.resolution_type
                      ? resolutionLabel(item.resolution_type)
                      : "Unresolved"}
                  </span>
                  <p>{item.resolution_note || "No resolution note yet."}</p>
                  {item.resolved_at && (
                    <small>
                      Updated by {item.resolved_by || "Unknown user"} ·{" "}
                      {new Date(item.resolved_at).toLocaleString()}
                    </small>
                  )}
                </div>
              </article>
            );
          })}
          {data.items.length === 0 && (
            <div className="empty-state">This case has no actionable items.</div>
          )}
        </div>
      </section>

      <section className="case-section">
        <div className="case-section-heading">
          <div>
            <span className="eyebrow">IMMUTABLE RESULT</span>
            <h3>Reconciliation lines</h3>
          </div>
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
              {immutableLines.map(({ key, line }) => (
                <tr key={key}>
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
        {immutableLines.length === 0 && (
          <div className="empty-state">No reconciliation lines.</div>
        )}
      </section>

      <section className="case-section">
        <div className="case-section-heading">
          <div>
            <span className="eyebrow">AUDIT TRAIL</span>
            <h3>Action history</h3>
          </div>
        </div>
        <ol className="case-history">
          {data.actions.map(({ action, actor_username }) => (
            <li key={action.action_id}>
              <div className="case-history-marker" />
              <div className="case-history-content">
                <div>
                  <strong>{caseActionLabel(action.action)}</strong>
                  <time>{new Date(action.created_at).toLocaleString()}</time>
                </div>
                <p>By {actor_username}</p>
                {action.reason && <p className="case-history-reason">{action.reason}</p>}
                {(action.old_value !== null || action.new_value !== null) && (
                  <details>
                    <summary>Recorded change</summary>
                    <pre>
                      {formatAuditValue(action.old_value)} →{" "}
                      {formatAuditValue(action.new_value)}
                    </pre>
                  </details>
                )}
              </div>
            </li>
          ))}
        </ol>
        {data.actions.length === 0 && (
          <div className="empty-state">No actions have been recorded.</div>
        )}
      </section>
    </section>
  );
}

function SummaryMetric({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <strong>{value}</strong>
      <span>{label}</span>
    </div>
  );
}

function caseItemLabel(itemType: CaseItemType): string {
  switch (itemType) {
    case "line":
      return "Line difference";
    case "purchase_order_conflict":
      return "Purchase order conflict";
    case "currency_conflict":
      return "Currency conflict";
  }
}

function caseItemDescription(itemType: CaseItemType): string {
  switch (itemType) {
    case "line":
      return "The linked reconciliation line is unavailable.";
    case "purchase_order_conflict":
      return "Invoice and Receive Note purchase orders do not match.";
    case "currency_conflict":
      return "Invoice and Receive Note currencies do not match.";
  }
}

function caseActionLabel(action: CaseActionType): string {
  switch (action) {
    case "created":
      return "Case created";
    case "claimed":
      return "Case claimed";
    case "reassigned":
      return "Case reassigned";
    case "resolution_changed":
      return "Resolution changed";
    case "submitted_for_approval":
      return "Submitted for approval";
    case "submitted_for_void":
      return "Submitted for void";
    case "returned":
      return "Case returned";
    case "approved":
      return "Case approved";
    case "voided":
      return "Case voided";
  }
}

function formatAuditValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}
