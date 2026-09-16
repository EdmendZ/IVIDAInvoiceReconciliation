import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client";
import {
  confirm, createIdempotencyKey, editDocument, getActions, getDocument, getRuntime,
  investigate, listDocuments, reopen, retry, selectReceivings, uploadDocument, voidDocument,
} from "./workspaceClient";

const response = (body: unknown = {}) =>
  new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
const summary = { document_id: "doc-1" };

describe("workspace client", () => {
  afterEach(() => vi.restoreAllMocks());

  it("uses workspace paths and preserves literal list filters", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(response({ items: [], page: 1, page_size: 20, total: 0 }));
    await listDocuments({ type: "invoice", status: ["needs_attention", "completed"], q: "  ACME  ", page: 2, page_size: 10 });
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe("/api/workspace/documents?type=invoice&status=needs_attention&status=completed&q=++ACME++&page=2&page_size=10");
  });

  it("sends every mutation with a caller-reusable idempotency key", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async () => response(summary));
    const options = { idempotencyKey: "11111111-1111-4111-8111-111111111111" };
    const command = { expected_revision: 2, reason: "reviewed" };
    await editDocument("doc/1", { ...command, document: { document_type: "invoice", document_number: "INV-1", document_date: null, purchase_order_number: null, currency: "AUD", supplier: null, location: null, subtotal: null, tax_total: null, total: null, items: [] } }, options);
    await selectReceivings("doc/1", { ...command, receive_document_ids: ["rn-1"] }, options);
    await investigate("doc/1", { expected_revision: 2, note: "follow up" }, options);
    await confirm("doc/1", { expected_revision: 2, preview_id: "preview-1", acknowledged_sources: true, acknowledged_unverified_dimensions: ["tax"], resolution: "matched", note: null }, options);
    await reopen("doc/1", command, options);
    await voidDocument("doc/1", command, options);
    await retry("doc/1", { expected_revision: 2 }, options);
    for (const call of fetchMock.mock.calls) {
      expect(new Headers(call[1]?.headers).get("Idempotency-Key")).toBe(options.idempotencyKey);
    }
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe("/api/workspace/documents/doc%2F1");
    expect(fetchMock.mock.calls.map(([path, init]) => `${init?.method}:${String(path)}`)).toEqual([
      "PATCH:/api/workspace/documents/doc%2F1", "PUT:/api/workspace/documents/doc%2F1/selection", "POST:/api/workspace/documents/doc%2F1/investigate",
      "POST:/api/workspace/documents/doc%2F1/confirm", "POST:/api/workspace/documents/doc%2F1/reopen", "POST:/api/workspace/documents/doc%2F1/void", "POST:/api/workspace/documents/doc%2F1/retry",
    ]);
  });

  it("uploads multipart data to the workspace endpoint and generates UUID keys", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(response({ document: summary, task_id: "task-1", run_id: "run-1", duplicate: false }));
    await uploadDocument({ file: new Blob(["pdf"]), filename: "invoice.pdf", document_type: "invoice" });
    const [path, init] = fetchMock.mock.calls[0]!;
    expect(path).toBe("/api/workspace/documents");
    expect(init?.method).toBe("POST");
    expect(new Headers(init?.headers).get("Idempotency-Key")).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    expect(init?.body).toBeInstanceOf(FormData);
  });

  it("uses read-only helpers for detail, actions, runtime and error metadata", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(response({})).mockResolvedValueOnce(response({})).mockResolvedValueOnce(response({}));
    await getDocument("doc-1");
    await getActions("doc-1", { page: 2, page_size: 5 });
    await getRuntime();
    expect(fetchMock.mock.calls.map(([path]) => String(path))).toEqual([
      "/api/workspace/documents/doc-1", "/api/workspace/documents/doc-1/actions?page=2&page_size=5", "/api/workspace/runtime",
    ]);

    vi.restoreAllMocks();
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ detail: { code: "REVISION_CONFLICT", message: "单据已更新，请查看最新内容", document_id: "doc-1", current_revision: 7 } }), { status: 409 }));
    await expect(getDocument("doc-1")).rejects.toEqual(new ApiError("单据已更新，请查看最新内容", 409, "REVISION_CONFLICT", "doc-1", 7));
  });

  it("creates RFC UUID keys through secure browser randomness", () => {
    expect(createIdempotencyKey()).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  });
});
