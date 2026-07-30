import { FormEvent, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, uploadDocument } from "../api/client";

type ExtractionTask = {
  task_id: string;
  document_type: "invoice" | "receive_note";
  original_filename: string;
  purchase_order_hint: string | null;
  status: string;
  error_message: string | null;
  size_bytes: number;
  created_at: string;
};

type ExtractionRun = {
  run_id: string;
  status: string;
  phase_error_code: string | null;
  error_message: string | null;
  attempt_count: number;
  created_at: string;
};

type TaskListItem = {
  task: ExtractionTask;
  latest_run: ExtractionRun | null;
};

export function UploadPage({
  onNavigate,
}: {
  onNavigate: (path: string) => void;
}) {
  const queryClient = useQueryClient();
  const [documentType, setDocumentType] = useState<"invoice" | "receive_note">(
    "invoice",
  );
  const [purchaseOrder, setPurchaseOrder] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [message, setMessage] = useState("");

  const tasks = useQuery({
    queryKey: ["extraction-tasks"],
    queryFn: () => api<TaskListItem[]>("/api/extraction-tasks?limit=50"),
    refetchInterval: 3000,
  });

  const startExtraction = useMutation({
    mutationFn: (taskId: string) =>
      api<ExtractionRun>(`/api/extraction-tasks/${taskId}/extract`, {
        method: "POST",
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["extraction-tasks"] });
    },
    onError: (problem) => {
      setMessage(problem instanceof Error ? problem.message : "Unable to start");
    },
  });

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!file) return;
    setMessage("");
    const body = new FormData();
    body.append("document_type", documentType);
    body.append("file", file);
    if (purchaseOrder.trim()) {
      body.append("purchase_order_hint", purchaseOrder.trim());
    }
    try {
      const task = await uploadDocument<ExtractionTask>(body);
      await startExtraction.mutateAsync(task.task_id);
      setFile(null);
      setPurchaseOrder("");
      const input = document.getElementById("document-file") as HTMLInputElement;
      if (input) input.value = "";
      setMessage(`${task.original_filename} uploaded and queued.`);
    } catch (problem) {
      setMessage(problem instanceof Error ? problem.message : "Upload failed");
    }
  }

  return (
    <section className="page">
      <div className="page-heading">
        <div>
          <span className="eyebrow">DOCUMENT INTAKE</span>
          <h2>Upload procurement documents</h2>
          <p>PDF, PNG and JPEG files up to 25 MB are accepted.</p>
        </div>
      </div>

      <div className="intake-layout">
        <form className="upload-card" onSubmit={submit}>
          <div className="segmented-control" aria-label="Document type">
            <button
              type="button"
              className={documentType === "invoice" ? "selected" : ""}
              onClick={() => setDocumentType("invoice")}
            >
              Invoice
            </button>
            <button
              type="button"
              className={documentType === "receive_note" ? "selected" : ""}
              onClick={() => setDocumentType("receive_note")}
            >
              Receive Note
            </button>
          </div>
          <label>
            Purchase order hint
            <input
              name="purchase_order_hint"
              placeholder="Optional, e.g. PO-7788"
              value={purchaseOrder}
              onChange={(event) => setPurchaseOrder(event.target.value)}
            />
          </label>
          <label className="file-drop">
            <span>{file ? file.name : "Choose a PDF or image"}</span>
            <small>
              {file
                ? `${(file.size / 1024 / 1024).toFixed(2)} MB`
                : "The original is stored privately in MinIO"}
            </small>
            <input
              id="document-file"
              name="file"
              type="file"
              accept=".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg"
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
              required
            />
          </label>
          <button
            className="primary"
            disabled={!file || startExtraction.isPending}
          >
            {startExtraction.isPending ? "Uploading…" : "Upload and process"}
          </button>
          {message && (
            <div
              className={
                message.includes("queued") ? "success-banner" : "error-banner"
              }
            >
              {message}
            </div>
          )}
        </form>

        <aside className="pipeline-card">
          <span className="eyebrow">PIPELINE</span>
          <h3>What happens next</h3>
          <ol className="pipeline-steps">
            <li><strong>Store</strong><span>Original file → MinIO</span></li>
            <li><strong>Parse</strong><span>MinerU → Markdown and tables</span></li>
            <li><strong>Normalize</strong><span>Text model → business fields</span></li>
            <li><strong>Validate</strong><span>GST and arithmetic rules</span></li>
            <li><strong>Review</strong><span>Human approval is mandatory</span></li>
          </ol>
        </aside>
      </div>

      <div className="section-heading">
        <div>
          <span className="eyebrow">RECENT ACTIVITY</span>
          <h3>Processing tasks</h3>
        </div>
        <button onClick={() => tasks.refetch()}>Refresh</button>
      </div>
      {tasks.error && (
        <div className="error-banner">{(tasks.error as Error).message}</div>
      )}
      <div className="task-list">
        {tasks.data?.map(({ task, latest_run: run }) => {
          const displayStatus = run?.status ?? task.status;
          const failed = displayStatus === "failed";
          return (
            <article className="task-row" key={task.task_id}>
              <div className={`task-icon ${task.document_type}`}>
                {task.document_type === "invoice" ? "INV" : "RN"}
              </div>
              <div className="task-main">
                <strong>{task.original_filename}</strong>
                <span>
                  {task.purchase_order_hint || "No PO hint"} ·{" "}
                  {(task.size_bytes / 1024).toFixed(0)} KB
                </span>
              </div>
              <div className="task-progress">
                <span className={`status ${displayStatus}`}>
                  {displayStatus.replaceAll("_", " ")}
                </span>
                {failed && (
                  <small>
                    {run?.phase_error_code || task.error_message || "Failed"}
                  </small>
                )}
              </div>
              <div className="task-actions">
                {(task.status === "uploaded" || failed) && (
                  <button
                    disabled={startExtraction.isPending}
                    onClick={() => startExtraction.mutate(task.task_id)}
                  >
                    {failed ? "Retry" : "Start"}
                  </button>
                )}
                {task.status === "ready_for_review" && (
                  <button className="primary" onClick={() => onNavigate("/")}>
                    Review
                  </button>
                )}
              </div>
            </article>
          );
        })}
      </div>
      {!tasks.isLoading && tasks.data?.length === 0 && (
        <div className="empty-state">No documents have been uploaded yet.</div>
      )}
    </section>
  );
}
