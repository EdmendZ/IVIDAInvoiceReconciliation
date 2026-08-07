import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, api, type User } from "../api/client";
import {
  canCompleteClaim,
  caseStatusLabel,
  queryForTab,
  type CaseQueueTab,
} from "./casePresentation";
import type { CaseDetail, CasePage, CaseSummary } from "./caseTypes";

const TABS: Array<{ id: CaseQueueTab; label: string }> = [
  { id: "unassigned", label: "Unassigned" },
  { id: "mine", label: "My work" },
  { id: "admin-decisions", label: "Admin decisions" },
  { id: "completed", label: "Completed" },
];

export function CaseQueuePage({
  user,
  onNavigate,
}: {
  user: User;
  onNavigate: (path: string) => void;
}) {
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<CaseQueueTab>("unassigned");
  const [page, setPage] = useState(1);
  const [invoiceDraft, setInvoiceDraft] = useState("");
  const [invoiceNumber, setInvoiceNumber] = useState("");
  const [claimingCaseId, setClaimingCaseId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const mountedRef = useRef(false);
  const activeClaimRef = useRef<string | null>(null);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const cases = useQuery({
    queryKey: ["reconciliation-cases", tab, page, invoiceNumber],
    queryFn: () =>
      api<CasePage>(
        `/api/reconciliation-cases?${queryForTab(tab, page, invoiceNumber)}`,
      ),
  });

  const totalPages = cases.data
    ? Math.max(1, Math.ceil(cases.data.total / cases.data.page_size))
    : 1;

  function selectTab(nextTab: CaseQueueTab) {
    setTab(nextTab);
    setPage(1);
    setError("");
  }

  async function claim(item: CaseSummary) {
    const requestedCaseId = item.case.case_id;
    if (activeClaimRef.current !== null) return;
    activeClaimRef.current = requestedCaseId;
    setClaimingCaseId(requestedCaseId);
    setError("");
    try {
      const updated = await api<CaseDetail>(
        `/api/reconciliation-cases/${encodeURIComponent(item.case.case_id)}/claim`,
        {
          method: "POST",
          body: JSON.stringify({ expected_revision: item.case.revision }),
        },
      );
      await queryClient.invalidateQueries({
        queryKey: ["reconciliation-cases"],
      });
      if (
        canCompleteClaim(
          mountedRef.current,
          requestedCaseId,
          activeClaimRef.current,
        )
      ) {
        activeClaimRef.current = null;
        setClaimingCaseId(null);
        onNavigate(`/cases/${encodeURIComponent(updated.case.case_id)}`);
      }
    } catch (problem) {
      if (
        problem instanceof ApiError &&
        ["CASE_ALREADY_CLAIMED", "CASE_REVISION_CONFLICT"].includes(
          problem.code ?? "",
        )
      ) {
        await queryClient.invalidateQueries({
          queryKey: ["reconciliation-cases"],
        });
      }
      if (
        canCompleteClaim(
          mountedRef.current,
          requestedCaseId,
          activeClaimRef.current,
        )
      ) {
        setError(problem instanceof Error ? problem.message : "Claim failed");
      }
    } finally {
      if (activeClaimRef.current === requestedCaseId) {
        activeClaimRef.current = null;
        if (mountedRef.current) setClaimingCaseId(null);
      }
    }
  }

  return (
    <section className="page">
      <div className="page-heading">
        <div>
          <span className="eyebrow">EXCEPTION CONTROL</span>
          <h2>Reconciliation cases</h2>
          <p>Claim abnormal reconciliations and follow their audit history.</p>
        </div>
        <button onClick={() => cases.refetch()}>Refresh</button>
      </div>

      <div className="case-toolbar">
        <div
          className="case-tabs"
          aria-label="Case queue filters"
          role="group"
        >
          {TABS.map((item) => (
            <button
              aria-pressed={tab === item.id}
              className={tab === item.id ? "active" : ""}
              key={item.id}
              onClick={() => selectTab(item.id)}
            >
              {item.label}
            </button>
          ))}
        </div>
        <form
          className="case-filter"
          onSubmit={(event) => {
            event.preventDefault();
            setInvoiceNumber(invoiceDraft.trim());
            setPage(1);
          }}
        >
          <label htmlFor="case-invoice-filter">Invoice Number</label>
          <div>
            <input
              id="case-invoice-filter"
              onChange={(event) => setInvoiceDraft(event.target.value)}
              placeholder="Exact number or prefix"
              value={invoiceDraft}
            />
            <button type="submit">Filter</button>
            {invoiceNumber && (
              <button
                className="case-filter-clear"
                onClick={() => {
                  setInvoiceDraft("");
                  setInvoiceNumber("");
                  setPage(1);
                }}
                type="button"
              >
                Clear
              </button>
            )}
          </div>
        </form>
      </div>

      {error && <div className="error-banner">{error}</div>}
      {cases.isLoading && <div className="empty-state">Loading cases…</div>}
      {cases.error && (
        <div className="error-banner">
          {cases.error instanceof Error
            ? cases.error.message
            : "Could not load reconciliation cases"}
        </div>
      )}

      <div className="case-grid">
        {cases.data?.items.map((item) => (
          <article className="case-card" key={item.case.case_id}>
            <div className="case-card-heading">
              <span className={`status ${item.case.status}`}>
                {caseStatusLabel(item.case.status)}
              </span>
              <span className="case-age">
                {new Date(item.case.created_at).toLocaleString()}
              </span>
            </div>
            <div>
              <h3>{item.invoice_number}</h3>
              <p>
                Receive Notes: {item.receive_note_numbers.join(", ") || "None"}
              </p>
            </div>
            <dl className="case-card-metrics">
              <div>
                <dt>Actionable items</dt>
                <dd>{item.actionable_count}</dd>
              </div>
              <div>
                <dt>Assignee</dt>
                <dd>{item.assignee_username || "Unassigned"}</dd>
              </div>
            </dl>
            <div className="case-card-actions">
              <button
                onClick={() =>
                  onNavigate(`/cases/${encodeURIComponent(item.case.case_id)}`)
                }
              >
                View details
              </button>
              {tab === "unassigned" && user.role === "reviewer" && (
                <button
                  className="primary"
                  disabled={claimingCaseId !== null}
                  onClick={() => claim(item)}
                >
                  {claimingCaseId === item.case.case_id ? "Claiming…" : "Claim"}
                </button>
              )}
            </div>
          </article>
        ))}
      </div>

      {!cases.isLoading && !cases.error && cases.data?.items.length === 0 && (
        <div className="empty-state">No cases match this queue and filter.</div>
      )}

      {cases.data && cases.data.total > 0 && (
        <div className="case-pagination" aria-label="Case queue pagination">
          <button
            disabled={page === 1}
            onClick={() => setPage((current) => Math.max(1, current - 1))}
          >
            Previous
          </button>
          <span>
            Page {cases.data.page} of {totalPages} · {cases.data.total} cases
          </span>
          <button
            disabled={page >= totalPages}
            onClick={() => setPage((current) => current + 1)}
          >
            Next
          </button>
        </div>
      )}
    </section>
  );
}
