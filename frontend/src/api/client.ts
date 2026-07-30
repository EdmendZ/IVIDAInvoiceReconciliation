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
