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
  const [messageSuccess, setMessageSuccess] = useState(false);

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
      setMessageSuccess(false);
      setMessage(problem instanceof Error ? problem.message : "无法启动");
    },
  });
  const cancelExtraction = useMutation({
    mutationFn: (runId: string) =>
      api<ExtractionRun>(`/api/extraction-runs/${runId}/cancel`, {
        method: "POST",
      }),
    onSuccess: async (run) => {
      setMessageSuccess(true);
      await queryClient.invalidateQueries({ queryKey: ["extraction-tasks"] });
      setMessage(
        run.status === "cancelled"
          ? "任务已取消。"
          : "已请求取消；当前外部调用结束后将停止后续处理。",
      );
    },
    onError: (problem) => {
      setMessageSuccess(false);
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
      setMessageSuccess(true);
      setMessage(`${task.original_filename} 已上传并进入处理队列。`);
    } catch (problem) {
      setMessageSuccess(false);
      setMessage(problem instanceof Error ? problem.message : "上传失败");
    }
  }

  return (
    <section className="page">
      <div className="page-heading">
        <div>
          <span className="eyebrow">单据录入</span>
          <h2>上传采购单据</h2>
          <p>
            上传供应商发票或外部收货单；通过集成接口导入的 TapTouch 收货记录无需上传文件。
          </p>
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
          <div className="segmented-control" aria-label="单据类型">
            <button
              type="button"
              className={documentType === "invoice" ? "selected" : ""}
              onClick={() => setDocumentType("invoice")}
            >
              发票
            </button>
            <button
              type="button"
              className={documentType === "receive_note" ? "selected" : ""}
              onClick={() => setDocumentType("receive_note")}
            >
              收货单
            </button>
          </div>
          <label>
            采购订单号线索
            <input
              name="purchase_order_hint"
              placeholder="选填，例如 PO-7788"
              value={purchaseOrder}
              onChange={(event) => setPurchaseOrder(event.target.value)}
            />
          </label>
          <label className="file-drop">
            <span>{file ? file.name : "选择 PDF 或图片"}</span>
            <small>
              {file
                ? `${(file.size / 1024 / 1024).toFixed(2)} MB`
                : "原件将安全保存，仅供授权访问"}
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
            {startExtraction.isPending ? "正在上传…" : "上传并处理"}
          </button>
          {message && (
            <div
              className={
                messageSuccess ? "success-banner" : "error-banner"
              }
            >
              {message}
            </div>
          )}
        </form>

        <aside className="pipeline-card">
          <span className="eyebrow">处理流程</span>
          <h3>后续处理步骤</h3>
          <ol className="pipeline-steps">
            <li><strong>保存</strong><span>安全保存原始文件</span></li>
            <li><strong>解析</strong><span>识别文字与表格</span></li>
            <li><strong>提取</strong><span>提取结构化业务字段</span></li>
            <li><strong>校验</strong><span>核验 GST 与金额计算</span></li>
            <li><strong>单据审核</strong><span>人工审核后方可对账</span></li>
          </ol>
        </aside>
      </div>

      <div className="section-heading">
        <div>
          <span className="eyebrow">近期记录</span>
          <h3>单据处理任务</h3>
        </div>
        <button onClick={() => tasks.refetch()}>刷新</button>
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
                {task.document_type === "invoice" ? "发票" : "收货"}
              </div>
              <div className="task-main">
                <strong>{task.original_filename}</strong>
                <span>
                  {task.purchase_order_hint || "未提供订单号"} ·{" "}
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
                    {run?.phase_error_code || task.error_message || "失败"}
                  </small>
                )}
              </div>
              <div className="task-actions">
                {(task.status === "uploaded" || failed) && (
                  <button
                    disabled={startExtraction.isPending}
                    onClick={() => startExtraction.mutate(task.task_id)}
                  >
                    {failed ? "重试" : "开始处理"}
                  </button>
                )}
                {task.status === "ready_for_review" && (
                  <button className="primary" onClick={() => onNavigate("/")}>
                    单据审核
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
        <div className="empty-state">尚未上传单据。</div>
      )}
    </section>
  );
}
