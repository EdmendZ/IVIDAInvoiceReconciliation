/**
 * 浏览器端统一 API 边界。
 *
 * 所有请求都携带 HttpOnly 会话 Cookie；业务页面不保存或读取令牌。401 被转换
 * 成全局事件，由应用壳统一退出登录，避免每个页面重复实现认证失效逻辑。
 */
export type User = {
  user_id: string;
  username: string;
  role: "reviewer" | "admin";
};

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code?: string,
  ) {
    super(message);
  }
}

export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await fetch(path, {
    ...options,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(options.headers ?? {}),
    },
  });
  if (response.status === 401) {
    window.dispatchEvent(new CustomEvent("ivida:unauthorized"));
  }
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => ({}));
    const detail =
      typeof body === "object" && body !== null && "detail" in body
        ? (body as { detail?: unknown }).detail
        : undefined;
    const structuredDetail =
      typeof detail === "object" && detail !== null
        ? (detail as { code?: unknown; message?: unknown })
        : undefined;
    const message =
      typeof detail === "string"
        ? detail
        : typeof structuredDetail?.message === "string"
          ? structuredDetail.message
          : `Request failed (${response.status})`;
    const code =
      typeof structuredDetail?.code === "string"
        ? structuredDetail.code
        : undefined;
    throw new ApiError(message, response.status, code);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return response.json() as Promise<T>;
}

export async function uploadDocument<T>(formData: FormData): Promise<T> {
  // 上传时不能手动设置 application/json；浏览器需要为 FormData 自动生成
  // 含 boundary 的 multipart Content-Type，否则后端无法拆出文件流和元数据。
  const response = await fetch("/api/documents/upload", {
    method: "POST",
    credentials: "include",
    body: formData,
  });
  if (response.status === 401) {
    window.dispatchEvent(new CustomEvent("ivida:unauthorized"));
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail ?? `Upload failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export async function downloadFile(path: string): Promise<void> {
  const response = await fetch(path, { credentials: "include" });
  if (response.status === 401) {
    window.dispatchEvent(new CustomEvent("ivida:unauthorized"));
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail ?? `Download failed (${response.status})`);
  }
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const filename = disposition.match(/filename="([^"]+)"/)?.[1] ?? "export.csv";
  const url = URL.createObjectURL(await response.blob());
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
