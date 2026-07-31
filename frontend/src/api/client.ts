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
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail ?? `Request failed (${response.status})`);
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
