import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, api, downloadFile, type User } from "../api/client";
import {
  adminActions,
  availableSubmission,
  canEditCase,
  canReassignCase,
  caseLineForItem,
  caseStatusLabel,
  resolutionLabel,
} from "./casePresentation";
import type {
  CaseActionType,
  CaseAssignee,
  CaseDetail,
  CaseItem,
  CaseItemType,
  ResolutionType,
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
  const queryClient = useQueryClient();
  const [busyItemId, setBusyItemId] = useState<string | null>(null);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [selectedAssignee, setSelectedAssignee] = useState("");
  const [reassignReason, setReassignReason] = useState("");
  const [returnOpen, setReturnOpen] = useState(false);
  const [returnReason, setReturnReason] = useState("");
  const [exporting, setExporting] = useState(false);
  const detail = useQuery({
    queryKey: ["reconciliation-case", caseId],
    queryFn: () =>
      api<CaseDetail>(
        `/api/reconciliation-cases/${encodeURIComponent(caseId)}`,
      ),
  });
  const reassignable = detail.data
    ? canReassignCase(detail.data.case, user)
    : false;
  const assignees = useQuery({
    queryKey: ["reconciliation-case-assignees"],
    queryFn: () =>
      api<CaseAssignee[]>("/api/reconciliation-cases/assignees"),
    enabled: reassignable,
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
  const editable = canEditCase(data.case, user);
  const submission = editable ? availableSubmission(data.items) : null;
  const decisions = adminActions(data.case, user);
  const result = data.reconciliation.result;
  const summary = result.summary;
  const lineResults = data.line_results ?? [];
  const readOnlyLines = result.lines
    .filter(
      (line) => line.status === "exact" || line.status === "within_tolerance",
    )
    .map((line) => ({ key: line.match_key, line }));

  async function handleMutationError(problem: unknown, fallback: string) {
    const refreshCodes = new Set([
      "CASE_REVISION_CONFLICT",
      "CASE_TERMINAL",
      "CASE_INVALID_TRANSITION",
      "CASE_ASSIGNEE_REQUIRED",
    ]);
    if (
      problem instanceof ApiError &&
      refreshCodes.has(problem.code ?? "")
    ) {
      await detail.refetch();
      setMessage(
        "This Case changed while you were viewing it. The latest version has been loaded.",
      );
      return;
    }
    setMessage(problem instanceof Error ? problem.message : fallback);
  }

  async function transition(
    action: "submit-approval" | "submit-void" | "approve" | "void",
  ) {
    setBusyAction(action);
    setMessage("");
    try {
      const updated = await api<CaseDetail>(
        `/api/reconciliation-cases/${encodeURIComponent(caseId)}/${action}`,
        {
          method: "POST",
          body: JSON.stringify({ expected_revision: data.case.revision }),
        },
      );
      queryClient.setQueryData(["reconciliation-case", caseId], updated);
    } catch (problem) {
      await handleMutationError(problem, "Case transition failed");
    } finally {
      setBusyAction(null);
    }
  }

  async function reassign() {
    if (!selectedAssignee || !reassignReason.trim()) return;
    setBusyAction("reassign");
    setMessage("");
    try {
      const updated = await api<CaseDetail>(
        `/api/reconciliation-cases/${encodeURIComponent(caseId)}/reassign`,
        {
          method: "POST",
          body: JSON.stringify({
            assignee_user_id: selectedAssignee,
            reason: reassignReason.trim(),
            expected_revision: data.case.revision,
          }),
        },
      );
      queryClient.setQueryData(["reconciliation-case", caseId], updated);
      setSelectedAssignee("");
      setReassignReason("");
    } catch (problem) {
      await handleMutationError(problem, "Reassignment failed");
    } finally {
      setBusyAction(null);
    }
  }

  async function returnCase() {
    if (!returnReason.trim()) return;
    setBusyAction("return");
    setMessage("");
    try {
      const updated = await api<CaseDetail>(
        `/api/reconciliation-cases/${encodeURIComponent(caseId)}/return`,
        {
          method: "POST",
          body: JSON.stringify({
            reason: returnReason.trim(),
            expected_revision: data.case.revision,
          }),
        },
      );
      queryClient.setQueryData(["reconciliation-case", caseId], updated);
      setReturnOpen(false);
      setReturnReason("");
    } catch (problem) {
      await handleMutationError(problem, "Return failed");
    } finally {
      setBusyAction(null);
    }
  }

  return (
    <section className="page case-detail-page">
      <div className="case-detail-toolbar">
        <button className="back-link" onClick={() => onNavigate("/cases")}>
          ← Back to Cases
        </button>
        <button
          disabled={exporting}
          onClick={async () => {
            setExporting(true);
            setMessage("");
            try {
              await downloadFile(
                `/api/reconciliations/${encodeURIComponent(data.case.reconciliation_id)}/export.csv`,
              );
            } catch (problem) {
              setMessage(
                problem instanceof Error ? problem.message : "Export failed",
              );
            } finally {
              setExporting(false);
            }
          }}
        >
          {exporting ? "Exporting…" : "Export CSV"}
        </button>
      </div>

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
        <SummaryMetric
          label="Purchase order"
          value={
            result.purchase_order_match === null
              ? "Unknown"
              : result.purchase_order_match
                ? "Match"
                : "Conflict"
          }
        />
        <SummaryMetric
          label="Currency"
          value={result.currency_match ? "Match" : "Conflict"}
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
                          <dt>Invoice quantity</dt>
                          <dd>{line.invoice_quantity}</dd>
                        </div>
                        <div>
                          <dt>Received quantity</dt>
                          <dd>{line.received_quantity}</dd>
                        </div>
                        <div>
                          <dt>Quantity difference</dt>
                          <dd>{line.quantity_difference}</dd>
                        </div>
                        <div>
                          <dt>Invoice unit price</dt>
                          <dd>{line.invoice_unit_price ?? "—"}</dd>
                        </div>
                        <div>
                          <dt>Received unit price</dt>
                          <dd>{line.received_unit_price ?? "—"}</dd>
                        </div>
                        <div>
                          <dt>Unit price difference</dt>
                          <dd>{line.unit_price_difference ?? "—"}</dd>
                        </div>
                        <div>
                          <dt>Invoice amount</dt>
                          <dd>{line.invoice_amount ?? "—"}</dd>
                        </div>
                        <div>
                          <dt>Received amount</dt>
                          <dd>{line.received_amount ?? "—"}</dd>
                        </div>
                        <div>
                          <dt>Amount difference</dt>
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
                <ItemResolution
                  disabled={busyItemId !== null || busyAction !== null}
                  editable={editable}
                  item={item}
                  saving={busyItemId === item.item_id}
                  onSave={async (resolutionType, note) => {
                    setBusyItemId(item.item_id);
                    setMessage("");
                    try {
                      const updated = await api<CaseDetail>(
                        `/api/reconciliation-cases/${encodeURIComponent(caseId)}/items/${encodeURIComponent(item.item_id)}/resolution`,
                        {
                          method: "PUT",
                          body: JSON.stringify({
                            resolution_type: resolutionType,
                            note: note.trim(),
                            expected_revision: data.case.revision,
                          }),
                        },
                      );
                      queryClient.setQueryData(
                        ["reconciliation-case", caseId],
                        updated,
                      );
                    } catch (problem) {
                      await handleMutationError(
                        problem,
                        "Resolution update failed",
                      );
                    } finally {
                      setBusyItemId(null);
                    }
                  }}
                />
              </article>
            );
          })}
          {data.items.length === 0 && (
            <div className="empty-state">This case has no actionable items.</div>
          )}
        </div>
      </section>

      {editable && (
        <section className="case-section case-decision-panel">
          <div>
            <span className="eyebrow">REVIEWER DECISION</span>
            <h3>Submit this Case</h3>
            {submission === null && (
              <p className="case-submission-guidance">
                {data.items.some(
                  (item) =>
                    item.resolution_type === "waiting_for_documents",
                )
                  ? "Waiting for documents must be resolved before this Case can be submitted."
                  : "Resolve every Case Item before submitting a decision."}
              </p>
            )}
          </div>
          {submission && (
            <button
              className={submission === "void" ? "danger" : "primary"}
              disabled={busyAction !== null || busyItemId !== null}
              onClick={() =>
                void transition(
                  submission === "approval"
                    ? "submit-approval"
                    : "submit-void",
                )
              }
            >
              {busyAction
                ? "Submitting…"
                : submission === "approval"
                  ? "Submit for approval"
                  : "Submit for void"}
            </button>
          )}
        </section>
      )}

      {reassignable && (
        <section className="case-section case-admin-panel">
          <div>
            <span className="eyebrow">ADMIN CONTROL</span>
            <h3>Reassign Case</h3>
            <p>Choose an active Reviewer and record why ownership changed.</p>
          </div>
          <form
            className="case-admin-form"
            onSubmit={(event) => {
              event.preventDefault();
              void reassign();
            }}
          >
            <label htmlFor="case-reassign-reviewer">
              Reviewer
              <select
                disabled={assignees.isLoading || busyAction !== null}
                id="case-reassign-reviewer"
                onChange={(event) => setSelectedAssignee(event.target.value)}
                value={selectedAssignee}
              >
                <option value="">Select an active Reviewer</option>
                {assignees.data?.map((assignee) => (
                  <option key={assignee.user_id} value={assignee.user_id}>
                    {assignee.username}
                  </option>
                ))}
              </select>
            </label>
            <label htmlFor="case-reassign-reason">
              Reassignment reason
              <textarea
                disabled={busyAction !== null}
                id="case-reassign-reason"
                onChange={(event) => setReassignReason(event.target.value)}
                rows={2}
                value={reassignReason}
              />
            </label>
            <button
              disabled={
                busyAction !== null ||
                !selectedAssignee ||
                !reassignReason.trim()
              }
              type="submit"
            >
              {busyAction === "reassign" ? "Reassigning…" : "Reassign Case"}
            </button>
            {assignees.error && (
              <p className="case-inline-error">
                {assignees.error instanceof Error
                  ? assignees.error.message
                  : "Could not load Reviewers"}
              </p>
            )}
          </form>
        </section>
      )}

      {decisions.length > 0 && (
        <section className="case-section case-admin-decision">
          <div>
            <span className="eyebrow">ADMIN DECISION</span>
            <h3>Review submitted decision</h3>
            <p>
              The service rechecks item resolutions and state before applying
              the decision.
            </p>
          </div>
          <div className="case-admin-decision-actions">
            {decisions.includes("approve") && (
              <button
                className="primary"
                disabled={busyAction !== null}
                onClick={() => void transition("approve")}
              >
                {busyAction === "approve" ? "Approving…" : "Approve Case"}
              </button>
            )}
            {decisions.includes("void") && (
              <button
                className="danger"
                disabled={busyAction !== null}
                onClick={() => void transition("void")}
              >
                {busyAction === "void" ? "Voiding…" : "Void Case"}
              </button>
            )}
            {decisions.includes("return") && !returnOpen && (
              <button
                disabled={busyAction !== null}
                onClick={() => setReturnOpen(true)}
              >
                Return Case
              </button>
            )}
          </div>
          {returnOpen && (
            <form
              className="case-return-form"
              onSubmit={(event) => {
                event.preventDefault();
                void returnCase();
              }}
            >
              <label htmlFor="case-return-reason">
                Return reason
                <textarea
                  disabled={busyAction !== null}
                  id="case-return-reason"
                  onChange={(event) => setReturnReason(event.target.value)}
                  rows={3}
                  value={returnReason}
                />
              </label>
              <div>
                <button
                  disabled={busyAction !== null}
                  onClick={() => {
                    setReturnOpen(false);
                    setReturnReason("");
                  }}
                  type="button"
                >
                  Cancel
                </button>
                <button
                  className="danger"
                  disabled={busyAction !== null || !returnReason.trim()}
                  type="submit"
                >
                  {busyAction === "return" ? "Returning…" : "Confirm return"}
                </button>
              </div>
            </form>
          )}
        </section>
      )}

      {message && <div className="error-banner">{message}</div>}

      <section className="case-section">
        <div className="case-section-heading">
          <div>
            <span className="eyebrow">IMMUTABLE RESULT</span>
            <h3>Exact and tolerance lines</h3>
          </div>
        </div>
        <div className="table-scroll">
          <table className="result-table">
            <thead>
              <tr>
                <th>Item</th>
                <th>Invoice qty</th>
                <th>Received qty</th>
                <th>Qty diff</th>
                <th>Invoice unit price</th>
                <th>Received unit price</th>
                <th>Unit price diff</th>
                <th>Invoice amount</th>
                <th>Received amount</th>
                <th>Amount diff</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {readOnlyLines.map(({ key, line }) => (
                <tr key={key}>
                  <td>
                    <strong>{line.sku || line.description}</strong>
                    {line.sku && <small>{line.description}</small>}
                  </td>
                  <td>{line.invoice_quantity}</td>
                  <td>{line.received_quantity}</td>
                  <td>{line.quantity_difference}</td>
                  <td>{line.invoice_unit_price ?? "—"}</td>
                  <td>{line.received_unit_price ?? "—"}</td>
                  <td>{line.unit_price_difference ?? "—"}</td>
                  <td>{line.invoice_amount ?? "—"}</td>
                  <td>{line.received_amount ?? "—"}</td>
                  <td>{line.amount_difference ?? "—"}</td>
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
        {readOnlyLines.length === 0 && (
          <div className="empty-state">No exact or within-tolerance lines.</div>
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

const RESOLUTIONS: ResolutionType[] = [
  "business_exception",
  "document_data_error",
  "matching_error",
  "waiting_for_documents",
];

function ItemResolution({
  disabled,
  editable,
  item,
  onSave,
  saving,
}: {
  disabled: boolean;
  editable: boolean;
  item: CaseItem;
  onSave: (resolutionType: ResolutionType, note: string) => Promise<void>;
  saving: boolean;
}) {
  const [resolutionType, setResolutionType] = useState<ResolutionType | "">(
    item.resolution_type ?? "",
  );
  const [note, setNote] = useState(item.resolution_note ?? "");

  useEffect(() => {
    setResolutionType(item.resolution_type ?? "");
    setNote(item.resolution_note ?? "");
  }, [item.resolution_type, item.resolution_note]);

  if (!editable) {
    return (
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
    );
  }

  const prefix = `case-item-${item.item_id}`;
  return (
    <form
      className="case-resolution-form"
      onSubmit={(event) => {
        event.preventDefault();
        if (resolutionType && note.trim()) void onSave(resolutionType, note);
      }}
    >
      <label htmlFor={`${prefix}-resolution`}>
        Resolution
        <select
          disabled={disabled}
          id={`${prefix}-resolution`}
          onChange={(event) =>
            setResolutionType(event.target.value as ResolutionType | "")
          }
          value={resolutionType}
        >
          <option value="">Select a resolution</option>
          {RESOLUTIONS.map((resolution) => (
            <option key={resolution} value={resolution}>
              {resolutionLabel(resolution)}
            </option>
          ))}
        </select>
      </label>
      <label htmlFor={`${prefix}-note`}>
        Resolution note
        <textarea
          disabled={disabled}
          id={`${prefix}-note`}
          onChange={(event) => setNote(event.target.value)}
          required
          rows={3}
          value={note}
        />
      </label>
      <button
        disabled={disabled || !resolutionType || !note.trim()}
        type="submit"
      >
        {saving ? "Saving…" : "Save resolution"}
      </button>
    </form>
  );
}

function SummaryMetric({
  label,
  value,
}: {
  label: string;
  value: number | string;
}) {
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
