import { FormEvent, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, uploadDocument } from "../api/client";
import { canCancelRun, presentTaskStatus } from "./taskPresentation";

/**
 * 上传页同时承担“创建任务”和“观察异步流水线”两种职责。
 *
 * 上传成功只代表原件已进入 MinIO、任务元数据已进入 PostgreSQL；随后显式调用
 * extract 创建 Run。模型工作由独立 Worker 消费，因此页面轮询任务和心跳，而
 * 不是让浏览器一直等待一个长 HTTP 请求。
 */
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
  cancel_requested_at: string | null;
  remote_may_continue: boolean;
  created_at: string;
};

type TaskListItem = {
  task: ExtractionTask;
  latest_run: ExtractionRun | null;
};

type RuntimeStatus = {
  api: "up";
  worker: "online" | "offline";
  worker_last_seen_at: string | null;
  worker_version: string | null;
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
  const runtime = useQuery({
    queryKey: ["runtime-status"],
    queryFn: () => api<RuntimeStatus>("/api/runtime/status"),
    refetchInterval: 5000,
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
  const cancelExtraction = useMutation({
    mutationFn: (runId: string) =>
      api<ExtractionRun>(`/api/extraction-runs/${runId}/cancel`, {
        method: "POST",
      }),
    onSuccess: async (run) => {
      await queryClient.invalidateQueries({ queryKey: ["extraction-tasks"] });
      setMessage(
        run.status === "cancelled"
          ? "任务已取消。"
          : "已请求取消；当前外部调用结束后将停止后续处理。",
      );
    },
    onError: (problem) => {
      setMessage(problem instanceof Error ? problem.message : "取消失败");
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
      // 先持久化原件和 Task，再创建 Run。若第二步失败，Task 仍然保留为
      // uploaded，用户可点 Start 重试，不需要再次上传或产生重复对象。
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

      <div
        className={`runtime-banner ${
          runtime.data?.worker === "online" ? "online" : "offline"
        }`}
      >
        <strong>
          {runtime.data?.worker === "online"
            ? "处理服务在线"
            : "处理服务离线"}
        </strong>
        <span>
          {runtime.data?.worker === "online"
            ? "新任务将自动进入 MinerU 解析和模型字段提取。"
            : "文件仍可安全上传，但任务会保持排队，直到 Worker 启动。"}
        </span>
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
          // Task 是文件生命周期，Run 是某一次处理尝试。列表优先展示最新 Run，
          // 才能正确反映重试失败、取消中等状态。
          const displayStatus = run?.status ?? task.status;
          const failed = displayStatus === "failed";
          const workerOnline = runtime.data?.worker === "online";
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
                  {presentTaskStatus(displayStatus, workerOnline)}
                </span>
                {run?.cancel_requested_at && displayStatus !== "cancelled" && (
                  <small>正在等待当前外部调用结束后取消</small>
                )}
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
                {run && canCancelRun(run.status) && (
                  <button
                    className="danger-link"
                    disabled={cancelExtraction.isPending}
                    onClick={() => {
                      if (
                        window.confirm(
                          "确认取消此任务？原件和处理记录会保留。",
                        )
                      ) {
                        cancelExtraction.mutate(run.run_id);
                      }
                    }}
                  >
                    取消
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
