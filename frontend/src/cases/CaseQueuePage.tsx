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
  { id: "unassigned", label: "待认领" },
  { id: "mine", label: "我的待办" },
  { id: "admin-decisions", label: "管理员待审批" },
  { id: "completed", label: "已完成" },
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
        setError(problem instanceof Error ? problem.message : "认领失败");
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
          <span className="eyebrow">差异管理</span>
          <h2>对账差异处理单</h2>
          <p>认领对账异常，处理差异并查看审计历史。</p>
        </div>
        <button onClick={() => cases.refetch()}>刷新</button>
      </div>

      <div className="case-toolbar">
        <div
          className="case-tabs"
          aria-label="处理单筛选"
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
          <label htmlFor="case-invoice-filter">发票编号</label>
          <div>
            <input
              id="case-invoice-filter"
              onChange={(event) => setInvoiceDraft(event.target.value)}
              placeholder="完整编号或编号前缀"
              value={invoiceDraft}
            />
            <button type="submit">筛选</button>
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
                清除
              </button>
            )}
          </div>
        </form>
      </div>

      {error && <div className="error-banner">{error}</div>}
      {cases.isLoading && <div className="empty-state">正在加载处理单…</div>}
      {cases.error && (
        <div className="error-banner">
          {cases.error instanceof Error
            ? cases.error.message
            : "无法加载差异处理单"}
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
                收货单： {item.receive_note_numbers.join(", ") || "无"}
              </p>
            </div>
            <dl className="case-card-metrics">
              <div>
                <dt>待处理差异项</dt>
                <dd>{item.actionable_count}</dd>
              </div>
              <div>
                <dt>负责人</dt>
                <dd>{item.assignee_username || "待认领"}</dd>
              </div>
            </dl>
            <div className="case-card-actions">
              <button
                onClick={() =>
                  onNavigate(`/cases/${encodeURIComponent(item.case.case_id)}`)
                }
              >
                查看详情
              </button>
              {tab === "unassigned" && user.role === "reviewer" && (
                <button
                  className="primary"
                  disabled={claimingCaseId !== null}
                  onClick={() => claim(item)}
                >
                  {claimingCaseId === item.case.case_id ? "正在认领…" : "认领"}
                </button>
              )}
            </div>
          </article>
        ))}
      </div>

      {!cases.isLoading && !cases.error && cases.data?.items.length === 0 && (
        <div className="empty-state">当前列表与筛选条件下没有处理单。</div>
      )}

      {cases.data && cases.data.total > 0 && (
        <div className="case-pagination" aria-label="处理单分页">
          <button
            disabled={page === 1}
            onClick={() => setPage((current) => Math.max(1, current - 1))}
          >
            上一页
          </button>
          <span>
            页码 {cases.data.page} / {totalPages} · {cases.data.total} 个处理单
          </span>
          <button
            disabled={page >= totalPages}
            onClick={() => setPage((current) => current + 1)}
          >
            下一页
          </button>
        </div>
      )}
    </section>
  );
}
