import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { ApiError } from "../api/client";
import {
  createIdempotencyKey,
  getRuntime,
  listDocuments,
  uploadDocument,
} from "./workspaceClient";
import { displayStatusLabel } from "./workspacePresentation";
import type { DisplayStatus, DocumentType } from "./workspaceTypes";

const STATUS_OPTIONS: DisplayStatus[] = [
  "processing",
  "waiting_counterpart",
  "needs_attention",
  "awaiting_confirmation",
  "completed",
  "failed",
  "cancelled",
  "voided",
];

type UploadRetry = {
  key: string;
  file: File;
  documentType: DocumentType;
};

export function WorkspacePage({ onNavigate }: { onNavigate: (path: string) => void }) {
  const [documentType, setDocumentType] = useState<DocumentType>("invoice");
  const [status, setStatus] = useState<DisplayStatus | "">("");
  const [searchDraft, setSearchDraft] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [uploadType, setUploadType] = useState<DocumentType>("invoice");
  const [uploading, setUploading] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const uploadRetry = useRef<UploadRetry | null>(null);
  const fileInput = useRef<HTMLInputElement | null>(null);

  const runtime = useQuery({
    queryKey: ["workspace-runtime"],
    queryFn: getRuntime,
    refetchInterval: () => (document.hidden ? false : 5_000),
    refetchIntervalInBackground: false,
  });
  const documents = useQuery({
    queryKey: ["workspace-documents", documentType, status, search, page],
    queryFn: () => listDocuments({
      type: documentType,
      status: status ? [status] : [],
      q: search || null,
      page,
      page_size: 20,
    }),
    refetchInterval: () => (document.hidden ? false : 5_000),
    refetchIntervalInBackground: false,
  });

  useEffect(() => {
    const refreshOnVisible = () => {
      if (!document.hidden) {
        void runtime.refetch();
        void documents.refetch();
      }
    };
    document.addEventListener("visibilitychange", refreshOnVisible);
    return () => document.removeEventListener("visibilitychange", refreshOnVisible);
  }, [documents.refetch, runtime.refetch]);

  async function runUpload(operation: UploadRetry) {
    setUploading(true);
    setError("");
    setNotice("");
    try {
      const result = await uploadDocument({
        file: operation.file,
        filename: operation.file.name,
        document_type: operation.documentType,
        idempotencyKey: operation.key,
      });
      uploadRetry.current = null;
      setNotice(result.duplicate ? "该文件已上传，已打开现有单据。" : "上传成功，系统正在自动提取和核对。可离开此页面。 ");
      await documents.refetch();
      onNavigate(`/documents/${encodeURIComponent(result.document.document_id)}?uploaded=1`);
    } catch (problem) {
      if (problem instanceof ApiError) uploadRetry.current = null;
      else uploadRetry.current = operation;
      setError(problem instanceof Error ? problem.message : "上传失败");
    } finally {
      setUploading(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  function chooseType(nextType: DocumentType) {
    setDocumentType(nextType);
    setPage(1);
    setError("");
  }

  const totalPages = documents.data
    ? Math.max(1, Math.ceil(documents.data.total / documents.data.page_size))
    : 1;

  return (
    <section className="page workspace-page">
      <div className="page-heading workspace-heading">
        <div>
          <span className="eyebrow">日常单据核对</span>
          <h2>单据工作台</h2>
          <p>上传后系统会自动提取、关联和生成核对预览。</p>
        </div>
        <label className="workspace-upload-button">
          <span>{uploading ? "正在上传…" : "上传单据"}</span>
          <input
            accept="application/pdf,image/png,image/jpeg"
            disabled={uploading}
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (!file) return;
              const operation = { key: createIdempotencyKey(), file, documentType: uploadType };
              uploadRetry.current = operation;
              void runUpload(operation);
            }}
            ref={fileInput}
            type="file"
          />
        </label>
      </div>

      {runtime.data && !runtime.data.worker_online && (
        <div className="runtime-banner offline" role="status">
          <strong>自动处理服务暂时离线</strong>
          <span>已上传任务仍会保留；服务恢复后将继续处理。</span>
        </div>
      )}
      {runtime.error && (
        <div className="runtime-banner offline" role="status">
          <strong>无法获取自动处理状态</strong>
          <span>单据列表仍可查看，请稍后刷新。</span>
        </div>
      )}
      {notice && <div className="success-banner">{notice}</div>}
      {error && (
        <div className="error-banner">
          {error}
          {uploadRetry.current && (
            <button className="danger-link" disabled={uploading} onClick={() => void runUpload(uploadRetry.current!)}>
              重试同一次上传
            </button>
          )}
        </div>
      )}

      <section className="workspace-intake-card" aria-labelledby="upload-type-title">
        <div>
          <span className="eyebrow">单据类型</span>
          <h3 id="upload-type-title">本次上传的是</h3>
        </div>
        <div className="segmented-control" role="group" aria-label="上传类型">
          <button className={uploadType === "invoice" ? "selected" : ""} onClick={() => setUploadType("invoice")} type="button">发票</button>
          <button className={uploadType === "receive_note" ? "selected" : ""} onClick={() => setUploadType("receive_note")} type="button">收货单</button>
        </div>
        <p>每次选择一个 PDF、PNG 或 JPEG 文件。无需手动开始提取或核对。</p>
      </section>

      <div className="workspace-toolbar">
        <div className="workspace-tabs" role="group" aria-label="单据列表类型">
          <button aria-pressed={documentType === "invoice"} className={documentType === "invoice" ? "active" : ""} onClick={() => chooseType("invoice")}>发票</button>
          <button aria-pressed={documentType === "receive_note"} className={documentType === "receive_note" ? "active" : ""} onClick={() => chooseType("receive_note")}>未关联收货记录</button>
        </div>
        <form
          className="workspace-filters"
          onSubmit={(event) => {
            event.preventDefault();
            setSearch(searchDraft.trim());
            setPage(1);
          }}
        >
          <label>
            状态
            <select value={status} onChange={(event) => { setStatus(event.target.value as DisplayStatus | ""); setPage(1); }}>
              <option value="">全部状态</option>
              {STATUS_OPTIONS.map((value) => <option key={value} value={value}>{displayStatusLabel(value)}</option>)}
            </select>
          </label>
          <label>
            编号或供应商
            <input maxLength={100} onChange={(event) => setSearchDraft(event.target.value)} placeholder="输入英文原值搜索" value={searchDraft} />
          </label>
          <button type="submit">筛选</button>
        </form>
      </div>

      {documents.isLoading && <div className="empty-state">正在加载单据…</div>}
      {documents.error && <div className="error-banner">{documents.error instanceof Error ? documents.error.message : "无法加载单据列表"}</div>}
      <div className="workspace-list">
        {documents.data?.items.map((item) => (
          <button className="workspace-document-row" key={item.document_id} onClick={() => onNavigate(`/documents/${encodeURIComponent(item.document_id)}`)}>
            <span className={`document-type ${item.document_type}`}>{item.document_type === "invoice" ? "发票" : "收货单"}</span>
            <span className="workspace-document-main">
              <strong>{item.document_number || "尚未提取编号"}</strong>
              <small>{item.supplier_name || "尚未提取供应商"} · {item.document_date || "日期未知"}</small>
            </span>
            <span className={`status ${item.display_status}`}>{displayStatusLabel(item.display_status)}</span>
            {item.source_changed && <span className="source-change-pill">来源已更新</span>}
            <time dateTime={item.updated_at}>{new Date(item.updated_at).toLocaleString()}</time>
          </button>
        ))}
      </div>
      {!documents.isLoading && !documents.error && documents.data?.items.length === 0 && (
        <div className="empty-state">
          {documentType === "invoice" ? "当前筛选条件下没有发票。" : "当前没有未关联收货记录。收货单可以先于发票上传。"}
        </div>
      )}
      {documents.data && documents.data.total > 0 && (
        <div className="workspace-pagination" aria-label="单据分页">
          <button disabled={page === 1} onClick={() => setPage((value) => Math.max(1, value - 1))}>上一页</button>
          <span>第 {documents.data.page} / {totalPages} 页 · 共 {documents.data.total} 张</span>
          <button disabled={page >= totalPages} onClick={() => setPage((value) => value + 1)}>下一页</button>
        </div>
      )}
    </section>
  );
}
