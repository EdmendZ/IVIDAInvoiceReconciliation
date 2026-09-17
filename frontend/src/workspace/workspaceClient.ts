import { api, downloadFile, uploadDocument as uploadFile } from "../api/client";
import type {
  ActionPage,
  ConfirmCommand,
  ConfirmationResponse,
  ConfirmationPage,
  ConfirmationQuery,
  ConfirmationView,
  DocumentDetail,
  DocumentPage,
  DocumentQuery,
  DocumentSummary,
  EditCommand,
  IntakeResponse,
  InvestigateCommand,
  ReasonCommand,
  RetryResponse,
  RuntimeView,
  SelectionCommand,
  UploadDocumentInput,
  RevisionCommand,
  WorkspaceRequestOptions,
} from "./workspaceTypes";
export type { WorkspaceRequestOptions } from "./workspaceTypes";
type KeyInput = WorkspaceRequestOptions | undefined;

/** Generate once for an operation. Callers can pass the same key to retry an
 * uncertain request; this module never replays a failed request by itself. */
export function createIdempotencyKey(): string {
  const randomUUID = globalThis.crypto?.randomUUID;
  if (randomUUID) return randomUUID.call(globalThis.crypto);
  if (!globalThis.crypto?.getRandomValues) {
    throw new Error("Secure randomness is required for workspace mutations");
  }
  const bytes = new Uint8Array(16);
  globalThis.crypto.getRandomValues(bytes);
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

function keyFor(options: KeyInput): string {
  return options?.idempotencyKey ?? createIdempotencyKey();
}

function writeOptions(options: KeyInput): RequestInit {
  return { headers: { "Idempotency-Key": keyFor(options) } };
}

function documentPath(documentId: string, suffix = ""): string {
  return `/api/workspace/documents/${encodeURIComponent(documentId)}${suffix}`;
}

export function listDocuments(query: DocumentQuery = {}): Promise<DocumentPage> {
  const params = new URLSearchParams();
  if (query.type) params.set("type", query.type);
  for (const status of query.status ?? []) params.append("status", status);
  if (query.q != null) params.set("q", query.q);
  if (query.page != null) params.set("page", String(query.page));
  if (query.page_size != null) params.set("page_size", String(query.page_size));
  const suffix = params.toString();
  return api<DocumentPage>(`/api/workspace/documents${suffix ? `?${suffix}` : ""}`);
}

export function getDocument(documentId: string): Promise<DocumentDetail> {
  return api<DocumentDetail>(documentPath(documentId));
}

export function getActions(
  documentId: string,
  query: { page?: number; page_size?: number } = {},
): Promise<ActionPage> {
  const params = new URLSearchParams();
  if (query.page != null) params.set("page", String(query.page));
  if (query.page_size != null) params.set("page_size", String(query.page_size));
  const suffix = params.toString();
  return api<ActionPage>(`${documentPath(documentId, "/actions")}${suffix ? `?${suffix}` : ""}`);
}

export function uploadDocument(
  input: UploadDocumentInput,
): Promise<IntakeResponse> {
  const nameFromBlob = "name" in input.file && typeof input.file.name === "string"
    ? input.file.name
    : "document";
  const form = new FormData();
  form.append("document_type", input.document_type);
  form.append("file", input.file, input.filename ?? nameFromBlob);
  return uploadFile<IntakeResponse>(
    form,
    "/api/workspace/documents",
    { "Idempotency-Key": keyFor({ idempotencyKey: input.idempotencyKey }) },
  );
}

export function editDocument(
  documentId: string,
  command: EditCommand,
  options?: KeyInput,
): Promise<DocumentSummary> {
  return api<DocumentSummary>(documentPath(documentId), {
    method: "PATCH",
    ...writeOptions(options),
    body: JSON.stringify(command),
  });
}

export function selectReceivings(
  documentId: string,
  command: SelectionCommand,
  options?: KeyInput,
): Promise<DocumentSummary> {
  return api<DocumentSummary>(documentPath(documentId, "/selection"), {
    method: "PUT",
    ...writeOptions(options),
    body: JSON.stringify(command),
  });
}

export function investigate(
  documentId: string,
  command: InvestigateCommand,
  options?: KeyInput,
): Promise<DocumentSummary> {
  return api<DocumentSummary>(documentPath(documentId, "/investigate"), {
    method: "POST",
    ...writeOptions(options),
    body: JSON.stringify(command),
  });
}

export function confirm(
  documentId: string,
  command: ConfirmCommand,
  options?: KeyInput,
): Promise<ConfirmationResponse> {
  return api<ConfirmationResponse>(documentPath(documentId, "/confirm"), {
    method: "POST",
    ...writeOptions(options),
    body: JSON.stringify(command),
  });
}

export function reopen(
  documentId: string,
  command: ReasonCommand,
  options?: KeyInput,
): Promise<DocumentSummary> {
  return api<DocumentSummary>(documentPath(documentId, "/reopen"), {
    method: "POST",
    ...writeOptions(options),
    body: JSON.stringify(command),
  });
}

export function voidDocument(
  documentId: string,
  command: ReasonCommand,
  options?: KeyInput,
): Promise<DocumentSummary> {
  return api<DocumentSummary>(documentPath(documentId, "/void"), {
    method: "POST",
    ...writeOptions(options),
    body: JSON.stringify(command),
  });
}

export function retry(
  documentId: string,
  command: RevisionCommand,
  options?: KeyInput,
): Promise<RetryResponse> {
  return api<RetryResponse>(documentPath(documentId, "/retry"), {
    method: "POST",
    ...writeOptions(options),
    body: JSON.stringify(command),
  });
}

export function getConfirmation(confirmationId: string): Promise<ConfirmationView> {
  return api<ConfirmationView>(`/api/workspace/confirmations/${encodeURIComponent(confirmationId)}`);
}

export function listConfirmations(query: ConfirmationQuery = {}): Promise<ConfirmationPage> {
  const params = new URLSearchParams();
  if (query.q != null) params.set("q", query.q);
  for (const outcome of query.outcome ?? []) params.append("outcome", outcome);
  if (query.page != null) params.set("page", String(query.page));
  if (query.page_size != null) params.set("page_size", String(query.page_size));
  const suffix = params.toString();
  return api<ConfirmationPage>(`/api/workspace/confirmations${suffix ? `?${suffix}` : ""}`);
}

export function exportConfirmation(confirmationId: string): Promise<void> {
  return downloadFile(
    `/api/workspace/confirmations/${encodeURIComponent(confirmationId)}/export.csv`,
  );
}

export function getRuntime(): Promise<RuntimeView> {
  return api<RuntimeView>("/api/workspace/runtime");
}

export const workspaceClient = {
  listDocuments,
  getDocument,
  getActions,
  uploadDocument,
  editDocument,
  selectReceivings,
  investigate,
  confirm,
  reopen,
  voidDocument,
  retry,
  listConfirmations,
  getConfirmation,
  exportConfirmation,
  getRuntime,
};
