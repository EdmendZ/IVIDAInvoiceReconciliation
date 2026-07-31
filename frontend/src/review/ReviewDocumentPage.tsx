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
    if (!detail.data || detail.data.version.status !== "draft") return;
    let document: Record<string, unknown>;
    try {
      const parsed: unknown = JSON.parse(editor);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        throw new Error("Document must be a JSON object");
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
            message: "Document JSON is invalid",
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
            : "Live validation failed",
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
      setMessage(problem instanceof Error ? problem.message : "Save failed");
    } finally {
      setBusy(false);
    }
  }

  async function decide(action: "approve" | "reject") {
    const reason =
      action === "reject"
        ? window.prompt("Why is this document rejected?") ?? ""
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
      setMessage(problem instanceof Error ? problem.message : "Action failed");
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
        ? "Invoice"
        : "Receive Note";
    const nextLabel =
      selectedType === "invoice" ? "Invoice" : "Receive Note";
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
        problem instanceof Error ? problem.message : "Reclassification failed",
      );
    } finally {
      setBusy(false);
    }
  }

  if (detail.isLoading) return <div className="loading">Loading document…</div>;
  if (!detail.data) return <div className="error-banner">Document not found.</div>;

  return (
    <section className="page">
      <button className="back-link" onClick={() => onNavigate("/")}>
        ← Review queue
      </button>
      <div className="review-heading">
        <div>
          <span className="eyebrow">VERSION {detail.data.version.version_number}</span>
          <h2>
            {String(
              detail.data.version.document_json.document_number ??
                "Untitled document",
            )}
          </h2>
        </div>
        <span className={`status ${detail.data.version.status}`}>
          {detail.data.version.status}
        </span>
      </div>
      <section className="type-control-card" aria-labelledby="document-type-title">
        <div>
          <span className="eyebrow">CLASSIFICATION CONTROL</span>
          <h3 id="document-type-title">Confirm the source document type</h3>
          <p>
            Approval confirms this classification. If it is wrong, reclassify
            the draft before approving it.
          </p>
        </div>
        <div className="type-control-actions">
          <label htmlFor="review-document-type">
            Document type
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
              <option value="invoice">Invoice</option>
              <option value="receive_note">Receive Note</option>
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
            Reclassify as new version
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
            I checked the source and confirm this is a{" "}
            <strong>
              {selectedType === "invoice" ? "Invoice" : "Receive Note"}
            </strong>
            .
          </label>
        ) : (
          <div className="type-warning">
            Save the new classification before approval.
          </div>
        )}
      </section>
      <div className="review-layout">
        <aside className="source-panel">
          <h3>Source evidence</h3>
          {detail.data.model_run && (
            <details className="model-run-panel">
              <summary>Model run</summary>
              <dl>
                <div>
                  <dt>Parser</dt>
                  <dd>
                    {detail.data.model_run.parser_provider ?? "Unknown"} /{" "}
                    {detail.data.model_run.parser_model ?? "Unknown"}
                  </dd>
                </div>
                <div>
                  <dt>Normalizer</dt>
                  <dd>
                    {detail.data.model_run.normalizer_provider ?? "Unknown"} /{" "}
                    {detail.data.model_run.normalizer_model ?? "Unknown"}
                  </dd>
                </div>
                <div>
                  <dt>Prompt</dt>
                  <dd>
                    {detail.data.model_run.prompt_version ?? "Not recorded"}
                  </dd>
                </div>
                <div>
                  <dt>Tokens</dt>
                  <dd>
                    {presentTokens(
                      detail.data.model_run.input_tokens,
                      detail.data.model_run.output_tokens,
                    )}
                  </dd>
                </div>
                <div>
                  <dt>Normalization</dt>
                  <dd>
                    {presentLatency(
                      detail.data.model_run.normalization_latency_ms,
                    )}
                  </dd>
                </div>
                <div>
                  <dt>Estimated cost</dt>
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
              <span>{item.page ? `Page ${item.page}` : "Page unknown"}</span>
              <p>{item.source_text}</p>
            </article>
          ))}
          {!detail.data.evidence.length && <p>No evidence was extracted.</p>}
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
            <h3>Live validation</h3>
            {validationBusy && <span>Checking…</span>}
          </div>
          {validationPreview && (
            <div className="validation-summary">
              <strong>{validationPreview.blocking_count}</strong> blocking ·{" "}
              <strong>{validationPreview.warning_count}</strong> warning
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
              <p>{issue.message}</p>
              {issue.measured_difference && (
                <small>Difference: {issue.measured_difference}</small>
              )}
            </article>
          ))}
          {!displayedIssues.length && !validationBusy && (
            <div className="success-banner">All current checks passed.</div>
          )}
        </aside>
      </div>
      {message && <div className="error-banner">{message}</div>}
      <footer className="action-bar">
        <button disabled={busy} onClick={save}>Save as new version</button>
        <button
          className="danger"
          disabled={busy || detail.data.version.status !== "draft"}
          onClick={() => decide("reject")}
        >
          Reject
        </button>
        <button
          className="primary"
          disabled={
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
          Approve
        </button>
      </footer>
    </section>
  );
}
