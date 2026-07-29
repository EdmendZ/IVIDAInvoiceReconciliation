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
}: {
  onNavigate: (path: string) => void;
}) {
  const queryClient = useQueryClient();
  const queue = useQuery({
    queryKey: ["review-queue"],
    queryFn: () => api<QueueItem[]>("/api/review/tasks"),
  });

  async function open(item: QueueItem) {
    let versionId = item.version_id;
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
          <span className="eyebrow">CONTROL QUEUE</span>
          <h2>Documents awaiting review</h2>
          <p>Approve only after checking source evidence and validation flags.</p>
        </div>
        <button onClick={() => queue.refetch()}>Refresh</button>
      </div>
      {queue.isLoading && <div className="empty-state">Loading queue…</div>}
      {queue.error && (
        <div className="error-banner">{(queue.error as Error).message}</div>
      )}
      <div className="queue-grid">
        {queue.data?.map((item) => (
          <button
            className="queue-card"
            key={item.task_id}
            onClick={() => open(item)}
          >
            <div className="queue-card-top">
              <span className={`document-type ${item.document_type}`}>
                {item.document_type.replace("_", " ")}
              </span>
              <span className={`status ${item.status}`}>{item.status}</span>
            </div>
            <h3>{item.document_number || "Document number not extracted"}</h3>
            <p>{item.supplier || "Supplier not extracted"}</p>
            <div className="issue-counts">
              <span className={item.blocking_count ? "blocking" : ""}>
                {item.blocking_count} blocking
              </span>
              <span>{item.warning_count} warnings</span>
            </div>
          </button>
        ))}
      </div>
      {!queue.isLoading && queue.data?.length === 0 && (
        <div className="empty-state">No documents are waiting for review.</div>
      )}
    </section>
  );
}
