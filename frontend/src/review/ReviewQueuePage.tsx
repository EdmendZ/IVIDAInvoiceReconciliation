import { label } from "../i18n";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";

type QueueItem = {
  task_id: string;
  version_id: string | null;
  status: string;
  document_type: string;
  document_number: string | null;
  supplier: string | null;
  validation_state: string;
  blocking_count: number;
  warning_count: number;
  created_at: string;
};

export function ReviewQueuePage({
  onNavigate,
  readOnly = false,
}: {
  onNavigate: (path: string) => void;
  readOnly?: boolean;
}) {
  const queryClient = useQueryClient();
  const queue = useQuery({
    queryKey: ["review-queue"],
    queryFn: () => api<QueueItem[]>("/api/review/tasks"),
  });

  async function open(item: QueueItem) {
    let versionId = item.version_id;
    if (readOnly && !versionId) return;
    if (!versionId) {
      const version = await api<{ version_id: string }>(
        `/api/review/tasks/${item.task_id}/start`,
        { method: "POST" },
      );
      versionId = version.version_id;
      await queryClient.invalidateQueries({ queryKey: ["review-queue"] });
    }
    onNavigate(`/review/${versionId}`);
  }

  return (
    <section className="page">
      <div className="page-heading">
        <div>
          <span className="eyebrow">审核工作区</span>
          <h2>待审核单据</h2>
          <p>请核对原文证据及校验提示后再批准。</p>
        </div>
        <button onClick={() => queue.refetch()}>刷新</button>
      </div>
      {queue.isLoading && <div className="empty-state">正在加载审核列表…</div>}
      {queue.error && (
        <div className="error-banner">{(queue.error as Error).message}</div>
      )}
      <div className="queue-grid">
        {queue.data?.map((item) => (
          <button
            className="queue-card"
            disabled={readOnly && !item.version_id}
            key={item.task_id}
            onClick={() => open(item)}
          >
            <div className="queue-card-top">
              <span className={`document-type ${item.document_type}`}>
                {label(item.document_type)}
              </span>
              <span className={`status ${label(item.status)}`}>{label(item.status)}</span>
            </div>
            <h3>{item.document_number || "未提取单据编号"}</h3>
            <p>{item.supplier || "未提取供应商"}</p>
            <div className="issue-counts">
              <span className={item.blocking_count ? "blocking" : ""}>
                {item.blocking_count} 项阻断
              </span>
              <span>{item.warning_count} 项警告</span>
            </div>
          </button>
        ))}
      </div>
      {!queue.isLoading && queue.data?.length === 0 && (
        <div className="empty-state">暂无待审核单据。</div>
      )}
    </section>
  );
}
