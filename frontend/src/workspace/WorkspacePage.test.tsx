// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { WorkspacePage } from "./WorkspacePage";

function response(body: unknown, status = 200): Promise<Response> {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));
}

const summary = {
  document_id: "invoice-1",
  document_type: "invoice",
  source_kind: "upload",
  revision: 1,
  processing_status: "processing",
  display_status: "processing",
  document_number: "INV-ENGLISH-001",
  supplier_name: "English Foods Pty Ltd",
  document_date: "2026-09-16",
  selected_document_ids: [],
  source_changed: false,
  updated_at: "2026-09-16T00:00:00Z",
  error_code: null,
};

function renderPage(onNavigate = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><WorkspacePage onNavigate={onNavigate} /></QueryClientProvider>);
  return onNavigate;
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("WorkspacePage", () => {
  it("defaults to invoices, separates an offline worker from an empty list, and can show receive notes first", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const path = String(input);
      if (path === "/api/workspace/runtime") return response({ enabled: true, worker_online: false, last_sync_at: null, preview_lag_seconds: null });
      if (path.includes("type=invoice")) return response({ items: [summary], page: 1, page_size: 20, total: 1 });
      if (path.includes("type=receive_note")) return response({ items: [], page: 1, page_size: 20, total: 0 });
      throw new Error(`Unexpected request: ${path}`);
    });
    renderPage();

    expect(await screen.findByText("INV-ENGLISH-001")).toBeTruthy();
    expect(screen.getByText("自动处理服务暂时离线")).toBeTruthy();
    expect(fetchMock.mock.calls.some(([input]) => String(input).includes("type=invoice"))).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "未关联收货记录" }));
    expect(await screen.findByText("当前没有未关联收货记录。收货单可以先于发票上传。")).toBeTruthy();
    expect(screen.getByText("自动处理服务暂时离线")).toBeTruthy();
  });

  it("uploads one explicitly typed receive note and navigates without a manual start step", async () => {
    let uploadedForm: FormData | null = null;
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const path = String(input);
      if (path === "/api/workspace/runtime") return response({ enabled: true, worker_online: true, last_sync_at: "2026-09-16T00:00:00Z", preview_lag_seconds: 0 });
      if (path.startsWith("/api/workspace/documents?") && !init?.method) return response({ items: [], page: 1, page_size: 20, total: 0 });
      if (path === "/api/workspace/documents" && init?.method === "POST") {
        uploadedForm = init.body as FormData;
        return response({ document: { ...summary, document_id: "rn-1", document_type: "receive_note" }, task_id: "task-1", run_id: "run-1", duplicate: false }, 201);
      }
      throw new Error(`Unexpected request: ${path}`);
    });
    const navigate = renderPage();
    await screen.findByText("当前筛选条件下没有发票。");

    fireEvent.click(screen.getByRole("button", { name: "收货单" }));
    const fileInput = screen.getByLabelText(/上传单据/) as HTMLInputElement;
    fireEvent.change(fileInput, { target: { files: [new File(["image"], "receiving.png", { type: "image/png" })] } });

    await waitFor(() => expect(navigate).toHaveBeenCalledWith("/documents/rn-1"));
    expect(uploadedForm).not.toBeNull();
    expect((uploadedForm as unknown as FormData).get("document_type")).toBe("receive_note");
    const uploadCall = fetchMock.mock.calls.find(([input, init]) => String(input) === "/api/workspace/documents" && init?.method === "POST");
    expect(new Headers(uploadCall?.[1]?.headers).get("Idempotency-Key")).toMatch(/^[0-9a-f-]{36}$/);
    expect(screen.queryByRole("button", { name: /开始提取|开始核对/ })).toBeNull();
  });
});
