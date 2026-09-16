import { label, systemMessage } from "../i18n";
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
          ← 返回差异列表
        </button>
        <div className="empty-state">正在加载差异处理单…</div>
      </section>
    );
  }

  if (detail.error || !detail.data) {
    return (
      <section className="page">
        <button className="back-link" onClick={() => onNavigate("/cases")}>
          ← 返回差异列表
        </button>
        <div className="error-banner">
          {detail.error instanceof Error
            ? detail.error.message
            : "无法加载此差异处理单"}
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
        "此处理单已被更新，现已加载最新版本，请重新确认。",
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
      await handleMutationError(problem, "处理单状态变更失败");
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
      await handleMutationError(problem, "重新分派失败");
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
      await handleMutationError(problem, "退回失败");
    } finally {
      setBusyAction(null);
    }
  }

  return (
    <section className="page case-detail-page">
      <div className="case-detail-toolbar">
        <button className="back-link" onClick={() => onNavigate("/cases")}>
          ← 返回差异列表
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
                problem instanceof Error ? problem.message : "导出失败",
              );
            } finally {
              setExporting(false);
            }
          }}
        >
          {exporting ? "正在导出…" : "导出 CSV"}
        </button>
      </div>

      <div className="case-detail-heading">
        <div>
          <span className="eyebrow">对账差异处理</span>
          <h2>{result.invoice_number}</h2>
          <p>对应收货单 {result.receive_note_numbers.join(", ") || "无收货单"}</p>
        </div>
        <div className="case-detail-state">
          <span className={`status ${data.case.status}`}>
            {caseStatusLabel(data.case.status)}
          </span>
          <small>
            负责人：{" "}
            {data.assignee_username ||
              (data.case.assignee_user_id ? "已分派审核员" : "待认领")} ·{" "}
            修订版本 {data.case.revision}
          </small>
          <small>
            当前身份 {user.username} ({label(user.role)})
          </small>
        </div>
      </div>

      <div className="case-summary-grid">
        <SummaryMetric label="总行数" value={summary.total_lines} />
        <SummaryMetric label="完全匹配" value={summary.exact_lines} />
        <SummaryMetric label="容差内" value={summary.tolerance_lines} />
        <SummaryMetric label="不匹配" value={summary.mismatch_lines} />
        <SummaryMetric label="仅发票存在" value={summary.invoice_only_lines} />
        <SummaryMetric
          label="仅收货单存在"
          value={summary.receive_note_only_lines}
        />
        <SummaryMetric
          label="采购订单号"
          value={
            result.purchase_order_match === null
              ? "未知"
              : result.purchase_order_match
                ? "一致"
                : "冲突"
          }
        />
        <SummaryMetric
          label="币种"
          value={result.currency_match ? "一致" : "冲突"}
        />
      </div>

      <section className="case-section">
        <div className="case-section-heading">
          <div>
            <span className="eyebrow">待处理差异</span>
            <h3>差异项</h3>
          </div>
          <span>{data.items.length} 项</span>
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
                          <dt>发票数量</dt>
                          <dd>{line.invoice_quantity}</dd>
                        </div>
                        <div>
                          <dt>收货数量</dt>
                          <dd>{line.received_quantity}</dd>
                        </div>
                        <div>
                          <dt>数量差异</dt>
                          <dd>{line.quantity_difference}</dd>
                        </div>
                        <div>
                          <dt>发票单价</dt>
                          <dd>{line.invoice_unit_price ?? "—"}</dd>
                        </div>
                        <div>
                          <dt>收货单价</dt>
                          <dd>{line.received_unit_price ?? "—"}</dd>
                        </div>
                        <div>
                          <dt>单价差异</dt>
                          <dd>{line.unit_price_difference ?? "—"}</dd>
                        </div>
                        <div>
                          <dt>发票金额</dt>
                          <dd>{line.invoice_amount ?? "—"}</dd>
                        </div>
                        <div>
                          <dt>收货金额</dt>
                          <dd>{line.received_amount ?? "—"}</dd>
                        </div>
                        <div>
                          <dt>金额差异</dt>
                          <dd>{line.amount_difference ?? "—"}</dd>
                        </div>
                      </dl>
                      <small>
                        {label(line.status)}
                        {line.reasons.length ? ` · ${line.reasons.map(systemMessage).join("，")}` : ""}
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
                        "处置结果更新失败",
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
            <div className="empty-state">此处理单没有待处理差异。</div>
          )}
        </div>
      </section>

      {editable && (
        <section className="case-section case-decision-panel">
          <div>
            <span className="eyebrow">审核员处置</span>
            <h3>提交处理单</h3>
            {submission === null && (
              <p className="case-submission-guidance">
                {data.items.some(
                  (item) =>
                    item.resolution_type === "waiting_for_documents",
                )
                  ? "请先补齐所需单据并完成处置，再提交处理单。"
                  : "请先完成所有差异项的处置，再提交决定。"}
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
                ? "正在提交…"
                : submission === "approval"
                  ? "提交审批"
                  : "申请作废"}
            </button>
          )}
        </section>
      )}

      {reassignable && (
        <section className="case-section case-admin-panel">
          <div>
            <span className="eyebrow">管理员操作</span>
            <h3>重新分派</h3>
            <p>选择有效的审核员，并记录更换负责人的原因。</p>
          </div>
          <form
            className="case-admin-form"
            onSubmit={(event) => {
              event.preventDefault();
              void reassign();
            }}
          >
            <label htmlFor="case-reassign-reviewer">
              审核员
              <select
                disabled={assignees.isLoading || busyAction !== null}
                id="case-reassign-reviewer"
                onChange={(event) => setSelectedAssignee(event.target.value)}
                value={selectedAssignee}
              >
                <option value="">选择有效的审核员</option>
                {assignees.data?.map((assignee) => (
                  <option key={assignee.user_id} value={assignee.user_id}>
                    {assignee.username}
                  </option>
                ))}
              </select>
            </label>
            <label htmlFor="case-reassign-reason">
              重新分派原因
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
              {busyAction === "reassign" ? "正在分派…" : "重新分派"}
            </button>
            {assignees.error && (
              <p className="case-inline-error">
                {assignees.error instanceof Error
                  ? assignees.error.message
                  : "无法加载审核员列表"}
              </p>
            )}
          </form>
        </section>
      )}

      {decisions.length > 0 && (
        <section className="case-section case-admin-decision">
          <div>
            <span className="eyebrow">管理员审批</span>
            <h3>审批已提交的处置结果</h3>
            <p>
              提交审批决定时，系统会重新核验差异处置结果与当前状态。
            </p>
          </div>
          <div className="case-admin-decision-actions">
            {decisions.includes("approve") && (
              <button
                className="primary"
                disabled={busyAction !== null}
                onClick={() => void transition("approve")}
              >
                {busyAction === "approve" ? "正在批准…" : "批准处理单"}
              </button>
            )}
            {decisions.includes("void") && (
              <button
                className="danger"
                disabled={busyAction !== null}
                onClick={() => void transition("void")}
              >
                {busyAction === "void" ? "正在作废…" : "作废处理单"}
              </button>
            )}
            {decisions.includes("return") && !returnOpen && (
              <button
                disabled={busyAction !== null}
                onClick={() => setReturnOpen(true)}
              >
                退回处理单
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
                退回原因
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
                  取消
                </button>
                <button
                  className="danger"
                  disabled={busyAction !== null || !returnReason.trim()}
                  type="submit"
                >
                  {busyAction === "return" ? "正在退回…" : "确认退回"}
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
            <span className="eyebrow">原始核对结果</span>
            <h3>完全匹配与容差内明细</h3>
          </div>
        </div>
        <div className="table-scroll">
          <table className="result-table">
            <thead>
              <tr>
                <th>商品</th>
                <th>发票数量</th>
                <th>收货数量</th>
                <th>数量差异</th>
                <th>发票单价</th>
                <th>收货单价</th>
                <th>单价差异</th>
                <th>发票金额</th>
                <th>收货金额</th>
                <th>金额差异</th>
                <th>状态</th>
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
                      {label(line.status)}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {readOnlyLines.length === 0 && (
          <div className="empty-state">没有完全匹配或容差内的明细。</div>
        )}
      </section>

      <section className="case-section">
        <div className="case-section-heading">
          <div>
            <span className="eyebrow">审计记录</span>
            <h3>操作历史</h3>
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
                <p>操作人 {actor_username}</p>
                {action.reason && <p className="case-history-reason">{action.reason}</p>}
                {(action.old_value !== null || action.new_value !== null) && (
                  <details>
                    <summary>变更记录</summary>
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
          <div className="empty-state">暂无操作记录。</div>
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
            : "未处置"}
        </span>
        <p>{item.resolution_note || "暂无处置说明。"}</p>
        {item.resolved_at && (
          <small>
            更新人 {item.resolved_by || "未知用户"} ·{" "}
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
        处置结论
        <select
          disabled={disabled}
          id={`${prefix}-resolution`}
          onChange={(event) =>
            setResolutionType(event.target.value as ResolutionType | "")
          }
          value={resolutionType}
        >
          <option value="">选择处置结论</option>
          {RESOLUTIONS.map((resolution) => (
            <option key={resolution} value={resolution}>
              {resolutionLabel(resolution)}
            </option>
          ))}
        </select>
      </label>
      <label htmlFor={`${prefix}-note`}>
        处置说明
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
        {saving ? "正在保存…" : "保存处置结果"}
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
      return "商品行差异";
    case "purchase_order_conflict":
      return "采购订单冲突";
    case "currency_conflict":
      return "币种冲突";
  }
}

function caseItemDescription(itemType: CaseItemType): string {
  switch (itemType) {
    case "line":
      return "关联的对账明细不可用。";
    case "purchase_order_conflict":
      return "发票与收货单的采购订单号不一致。";
    case "currency_conflict":
      return "发票与收货单的币种不一致。";
  }
}

function caseActionLabel(action: CaseActionType): string {
  switch (action) {
    case "created":
      return "已创建处理单";
    case "claimed":
      return "已认领处理单";
    case "reassigned":
      return "已重新分派";
    case "resolution_changed":
      return "已更新处置结果";
    case "submitted_for_approval":
      return "已提交审批";
    case "submitted_for_void":
      return "已申请作废";
    case "returned":
      return "已退回处理单";
    case "approved":
      return "已批准处理单";
    case "voided":
      return "已作废处理单";
  }
}

function formatAuditValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}
