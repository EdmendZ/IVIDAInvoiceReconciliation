import { label, systemMessage } from "../i18n";
import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { StructuredDocumentEditor } from "./StructuredDocumentEditor";
import {
  type ModelRun,
  presentCost,
  presentLatency,
  presentTokens,
} from "./modelRunPresentation";

/**
 * 单据审核页实现 Human-in-the-loop 边界。
 *
 * 模型结果先成为可修改 Draft。每次保存或重新分类都会创建不可变新版本；
 * 只有通过实时规则校验、确认单据类型并人工批准的版本，才能进入对账候选池。
 */
type Detail = {
  version: {
    version_id: string;
    version_number: number;
    status: string;
    document_type: "invoice" | "receive_note";
    document_json: Record<string, unknown>;
  };
  evidence: Array<{
    field_path: string;
    source_text: string;
    page: number | null;
  }>;
  issues: Array<{
    rule_code: string;
    severity: "blocking" | "warning";
    field_path: string;
    message: string;
    measured_difference?: string | null;
  }>;
  actions: Array<{ action: string; reason: string | null; created_at: string }>;
  model_run: ModelRun | null;
};

type LiveIssue = {
  rule_code: string;
  severity: "blocking" | "warning";
  field_path: string;
  message: string;
  measured_difference: string | null;
};

type ValidationPreview = {
  schema_valid: boolean;
  blocking_count: number;
  warning_count: number;
  issues: LiveIssue[];
};

export function ReviewDocumentPage({
  versionId,
  onNavigate,
}: {
  versionId: string;
  onNavigate: (path: string, replace?: boolean) => void;
}) {
  const detail = useQuery({
    queryKey: ["review-version", versionId],
    queryFn: () => api<Detail>(`/api/review/versions/${versionId}`),
  });
  const [editor, setEditor] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [selectedType, setSelectedType] = useState<
    "invoice" | "receive_note"
  >("invoice");
  const [typeConfirmed, setTypeConfirmed] = useState(false);
  const [validationPreview, setValidationPreview] =
    useState<ValidationPreview | null>(null);
  const [validationBusy, setValidationBusy] = useState(false);
  const [validationError, setValidationError] = useState("");

  useEffect(() => {
    if (detail.data) {
      setEditor(JSON.stringify(detail.data.version.document_json, null, 2));
      setSelectedType(detail.data.version.document_type);
      setTypeConfirmed(false);
    }
  }, [detail.data]);

  useEffect(() => {
    // 450ms 防抖避免用户每敲一个字符就请求后端。AbortController 取消过期请求，
    // 防止较早响应晚到并覆盖最新 JSON 对应的校验结果。
    if (!detail.data || detail.data.version.status !== "draft") return;
    let document: Record<string, unknown>;
    try {
      const parsed: unknown = JSON.parse(editor);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        throw new Error("单据内容必须为 JSON 对象");
      }
      document = parsed as Record<string, unknown>;
    } catch {
      setValidationPreview({
        schema_valid: false,
        blocking_count: 1,
        warning_count: 0,
        issues: [
          {
            rule_code: "JSON_INVALID",
            severity: "blocking",
            field_path: "document",
            message: "单据 JSON 无效",
            measured_difference: null,
          },
        ],
      });
      setValidationBusy(false);
      return;
    }

    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      setValidationBusy(true);
      setValidationError("");
      try {
        const preview = await api<ValidationPreview>(
          `/api/review/versions/${versionId}/validate`,
          {
            method: "POST",
            body: JSON.stringify({ document }),
            signal: controller.signal,
          },
        );
        setValidationPreview(preview);
      } catch (problem) {
        if (problem instanceof Error && problem.name === "AbortError") return;
        setValidationError(
          problem instanceof Error
            ? problem.message
            : "实时校验失败",
        );
        setValidationPreview(null);
      } finally {
        if (!controller.signal.aborted) setValidationBusy(false);
      }
    }, 450);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [detail.data, editor, versionId]);

  const displayedIssues = useMemo(
    () => validationPreview?.issues ?? detail.data?.issues ?? [],
    [detail.data, validationPreview],
  );

  async function save() {
    setBusy(true);
    setMessage("");
    try {
      // PATCH 并非原地覆盖：服务端会复制出下一版本并记录修订原因，从而保留
      // 模型原始输出和全部人工修改轨迹。
      const document = JSON.parse(editor);
      const next = await api<{ version_id: string }>(
        `/api/review/versions/${versionId}`,
        {
          method: "PATCH",
          body: JSON.stringify({ document, reason: "Reviewer correction" }),
        },
      );
      onNavigate(`/review/${next.version_id}`, true);
    } catch (problem) {
      setMessage(problem instanceof Error ? problem.message : "保存失败");
    } finally {
      setBusy(false);
    }
  }

  async function decide(action: "approve" | "reject") {
    const reason =
      action === "reject"
        ? window.prompt("请输入驳回原因") ?? ""
        : "Source document verified";
    if (action === "reject" && !reason.trim()) return;
    setBusy(true);
    try {
      await api(`/api/review/versions/${versionId}/${action}`, {
        method: "POST",
        body: JSON.stringify(
          action === "approve"
            ? {
                reason,
                confirmed_document_type: detail.data?.version.document_type,
              }
            : { reason },
        ),
      });
      onNavigate("/");
    } catch (problem) {
      setMessage(problem instanceof Error ? problem.message : "操作失败");
    } finally {
      setBusy(false);
    }
  }

  async function reclassify() {
    if (!detail.data || selectedType === detail.data.version.document_type) {
      return;
    }
    const currentLabel =
      detail.data.version.document_type === "invoice"
        ? "发票"
        : "收货单";
    const nextLabel =
      selectedType === "invoice" ? "发票" : "收货单";
    if (
      !window.confirm(
        `Change document type from ${currentLabel} to ${nextLabel}? A new audited version will be created.`,
      )
    ) {
      return;
    }
    setBusy(true);
    setMessage("");
    try {
      // 文档类型影响 Schema 与后续候选集合，所以纠错也必须产生审计版本，
      // 不能只在浏览器里改一个标签。
      const next = await api<{ version_id: string }>(
        `/api/review/versions/${versionId}/reclassify`,
        {
          method: "POST",
          body: JSON.stringify({
            document_type: selectedType,
            reason: "Reviewer corrected document type from source evidence",
          }),
        },
      );
      onNavigate(`/review/${next.version_id}`, true);
    } catch (problem) {
      setMessage(
        problem instanceof Error ? problem.message : "重新分类失败",
      );
    } finally {
      setBusy(false);
    }
  }

  if (detail.isLoading) return <div className="loading">正在加载单据…</div>;
  if (!detail.data) return <div className="error-banner">未找到单据。</div>;

  return (
    <section className="page">
      <button className="back-link" onClick={() => onNavigate("/")}>
        ← 返回审核列表
      </button>
      <div className="review-heading">
        <div>
          <span className="eyebrow">版本 {detail.data.version.version_number}</span>
          <h2>
            {String(
              detail.data.version.document_json.document_number ??
                "未命名单据",
            )}
          </h2>
        </div>
        <span className={`status ${label(detail.data.version.status)}`}>
          {detail.data.version.status}
        </span>
      </div>
      <section className="type-control-card" aria-labelledby="document-type-title">
        <div>
          <span className="eyebrow">单据分类</span>
          <h3 id="document-type-title">确认原始单据类型</h3>
          <p>
            批准即确认此单据类型。如类型有误，请先修改分类并保存。
          </p>
        </div>
        <div className="type-control-actions">
          <label htmlFor="review-document-type">
            单据类型
            <select
              id="review-document-type"
              name="document_type"
              value={selectedType}
              disabled={busy || detail.data.version.status !== "draft"}
              onChange={(event) => {
                setSelectedType(
                  event.target.value as "invoice" | "receive_note",
                );
                setTypeConfirmed(false);
              }}
            >
              <option value="invoice">发票</option>
              <option value="receive_note">收货单</option>
            </select>
          </label>
          <button
            disabled={
              busy ||
              detail.data.version.status !== "draft" ||
              selectedType === detail.data.version.document_type
            }
            onClick={reclassify}
          >
            保存分类为新版本
          </button>
        </div>
        {selectedType === detail.data.version.document_type ? (
          <label
            className="type-confirmation"
            htmlFor="confirm-document-type"
          >
            <input
              id="confirm-document-type"
              name="confirm_document_type"
              type="checkbox"
              checked={typeConfirmed}
              disabled={busy || detail.data.version.status !== "draft"}
              onChange={(event) => setTypeConfirmed(event.target.checked)}
            />
            我已核对原件，确认此单据为{" "}
            <strong>
              {selectedType === "invoice" ? "发票" : "收货单"}
            </strong>
            .
          </label>
        ) : (
          <div className="type-warning">
            请先保存新的单据分类，再批准。
          </div>
        )}
      </section>
      <div className="review-layout">
        <aside className="source-panel">
          <h3>原文证据</h3>
          {detail.data.model_run && (
            <details className="model-run-panel">
              <summary>模型运行信息</summary>
              <dl>
                <div>
                  <dt>解析器</dt>
                  <dd>
                    {detail.data.model_run.parser_provider ?? "未知"} /{" "}
                    {detail.data.model_run.parser_model ?? "未知"}
                  </dd>
                </div>
                <div>
                  <dt>字段提取模型</dt>
                  <dd>
                    {detail.data.model_run.normalizer_provider ?? "未知"} /{" "}
                    {detail.data.model_run.normalizer_model ?? "未知"}
                  </dd>
                </div>
                <div>
                  <dt>提示词版本</dt>
                  <dd>
                    {detail.data.model_run.prompt_version ?? "未记录"}
                  </dd>
                </div>
                <div>
                  <dt>Token 用量</dt>
                  <dd>
                    {presentTokens(
                      detail.data.model_run.input_tokens,
                      detail.data.model_run.output_tokens,
                    )}
                  </dd>
                </div>
                <div>
                  <dt>提取耗时</dt>
                  <dd>
                    {presentLatency(
                      detail.data.model_run.normalization_latency_ms,
                    )}
                  </dd>
                </div>
                <div>
                  <dt>估算成本</dt>
                  <dd>
                    {presentCost(detail.data.model_run.estimated_cost_aud)}
                  </dd>
                </div>
              </dl>
            </details>
          )}
          {detail.data.evidence.map((item, index) => (
            <article className="evidence" key={`${item.field_path}-${index}`}>
              <strong>{item.field_path}</strong>
              <span>{item.page ? `页码 ${item.page}` : "页码未知"}</span>
              <p>{item.source_text}</p>
            </article>
          ))}
          {!detail.data.evidence.length && <p>未提取到原文证据。</p>}
        </aside>
        <div className="editor-panel">
          <StructuredDocumentEditor
            editor={editor}
            evidence={detail.data.evidence}
            issues={displayedIssues}
            onChange={setEditor}
          />
        </div>
        <aside className="issues-panel">
          <div className="validation-heading">
            <h3>实时校验</h3>
            {validationBusy && <span>正在校验…</span>}
          </div>
          {validationPreview && (
            <div className="validation-summary">
              <strong>{validationPreview.blocking_count}</strong> 项阻断 ·{" "}
              <strong>{validationPreview.warning_count}</strong> 项警告
            </div>
          )}
          {validationError && (
            <div className="error-banner">{validationError}</div>
          )}
          {displayedIssues.map((issue, index) => (
            <article
              className={`issue ${issue.severity}`}
              key={`${issue.rule_code}-${issue.field_path}-${index}`}
            >
              <strong>{issue.rule_code}</strong>
              <span>{issue.field_path}</span>
              <p>{systemMessage(issue.message)}</p>
              {issue.measured_difference && (
                <small>差值： {issue.measured_difference}</small>
              )}
            </article>
          ))}
          {!displayedIssues.length && !validationBusy && (
            <div className="success-banner">当前所有校验均已通过。</div>
          )}
        </aside>
      </div>
      {message && <div className="error-banner">{message}</div>}
      <footer className="action-bar">
        <button disabled={busy} onClick={save}>保存为新版本</button>
        <button
          className="danger"
          disabled={busy || detail.data.version.status !== "draft"}
          onClick={() => decide("reject")}
        >
          驳回
        </button>
        <button
          className="primary"
          disabled={
            // 审批是严格业务门：校验未完成、有阻断项、类型未人工确认、
            // 类型尚未落盘或当前不是草稿，任一条件都不允许放行。
            busy ||
            validationBusy ||
            !validationPreview ||
            validationPreview.blocking_count > 0 ||
            !typeConfirmed ||
            selectedType !== detail.data.version.document_type ||
            detail.data.version.status !== "draft"
          }
          onClick={() => decide("approve")}
        >
          批准
        </button>
      </footer>
    </section>
  );
}
