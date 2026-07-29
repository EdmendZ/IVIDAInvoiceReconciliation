import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";

type Detail = {
  version: {
    version_id: string;
    version_number: number;
    status: string;
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
  }>;
  actions: Array<{ action: string; reason: string | null; created_at: string }>;
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

  useEffect(() => {
    if (detail.data) {
      setEditor(JSON.stringify(detail.data.version.document_json, null, 2));
    }
  }, [detail.data]);

  const blockers = useMemo(
    () => detail.data?.issues.filter((issue) => issue.severity === "blocking") ?? [],
    [detail.data],
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
        body: JSON.stringify({ reason }),
      });
      onNavigate("/");
    } catch (problem) {
      setMessage(problem instanceof Error ? problem.message : "Action failed");
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
      <div className="review-layout">
        <aside className="source-panel">
          <h3>Source evidence</h3>
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
          <h3>Structured document</h3>
          <textarea
            aria-label="Structured document JSON"
            value={editor}
            onChange={(event) => setEditor(event.target.value)}
            spellCheck={false}
          />
        </div>
        <aside className="issues-panel">
          <h3>Validation</h3>
          {detail.data.issues.map((issue) => (
            <article className={`issue ${issue.severity}`} key={issue.rule_code}>
              <strong>{issue.rule_code}</strong>
              <span>{issue.field_path}</span>
              <p>{issue.message}</p>
            </article>
          ))}
          {!detail.data.issues.length && (
            <div className="success-banner">No validation issues.</div>
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
            blockers.length > 0 ||
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
