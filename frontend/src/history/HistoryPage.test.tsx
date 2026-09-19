// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { HistoryPage } from "./HistoryPage";

function response(body: unknown, status = 200): Promise<Response> {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));
}

const summary = {
  confirmation_id: "confirmation-1",
  invoice_document_id: "invoice-1",
  invoice_number: "INV-HISTORY-100",
  supplier_name: "Southern Produce Pty Ltd",
  receive_note_numbers: ["RN-HISTORY-200"],
  resolution: "resolved_with_note",
  outcome: "difference",
  coverage: "quantity_only",
  acknowledged_unverified_dimensions: ["price", "amount", "document_total", "tax"],
  note: "Supplier confirmed a short delivery.",
  actor_id: "actor-1",
  created_at: "2026-09-17T01:00:00Z",
};

const detail = {
  confirmation_id: summary.confirmation_id,
  preview_id: "preview-1",
  invoice_number: summary.invoice_number,
  receive_note_numbers: summary.receive_note_numbers,
  resolution: summary.resolution,
  note: summary.note,
  acknowledged_unverified_dimensions: summary.acknowledged_unverified_dimensions,
  result_snapshot: {
    outcome: "difference",
    coverage: "quantity_only",
    blocking_codes: [],
    unverified_dimensions: summary.acknowledged_unverified_dimensions,
    lines: [{
      match_key: "sku:eggs|carton",
      sku: "EGGS-12",
      description: "Free Range Eggs 12 Pack",
      invoice_unit: "carton",
      received_unit: "carton",
      quantity: { invoice_value: "10", received_value: "8", difference: "2", status: "different", reason_code: null },
      price: { invoice_value: "4.50", received_value: null, difference: null, status: "unverified", reason_code: null },
      amount: { invoice_value: "45.00", received_value: null, difference: null, status: "unverified", reason_code: null },
      status: "different",
      reason_codes: [],
      invoice_line_indexes: [0],
      receive_lines: [{ document_id: "receiving-1", line_index: 0 }],
    }],
    summary: { total_lines: 1, different_lines: 1, unverified_lines: 1 },
    subject: { supplier: "equal", currency: "equal", scope: "equal" },
  },
  rule_version: "ir-simple-rules-1",
  tolerances: { quantity: "0", unit_price: "0.01", amount: "0.02" },
  input_revision_ids: ["revision-1", "revision-2"],
  actor_id: summary.actor_id,
  created_at: summary.created_at,
};

function renderPage(props: { confirmationId?: string; onNavigate?: (path: string) => void } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const onNavigate = props.onNavigate ?? vi.fn();
  render(<QueryClientProvider client={client}><HistoryPage confirmationId={props.confirmationId} onNavigate={onNavigate} /></QueryClientProvider>);
  return onNavigate;
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("HistoryPage", () => {
  it("shows immutable workspace history, filters it, and opens a snapshot", async () => {
    const requests: string[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const path = String(input);
      requests.push(path);
      return response({ items: [summary], page: 1, page_size: 20, total: 1 });
    });
    const navigate = renderPage();

    expect(await screen.findByText("INV-HISTORY-100")).toBeTruthy();
    expect(screen.getByText("Southern Produce Pty Ltd")).toBeTruthy();
    expect(screen.getByText("收货单：RN-HISTORY-200")).toBeTruthy();
    expect(screen.getByText("4 个未核验维度")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("搜索历史"), { target: { value: "RN-HISTORY-200" } });
    fireEvent.click(screen.getByRole("button", { name: "搜索" }));
    await waitFor(() => expect(requests.some((path) => path.includes("q=RN-HISTORY-200"))).toBe(true));
    fireEvent.change(screen.getByLabelText("核对结论"), { target: { value: "difference" } });
    await waitFor(() => expect(requests.some((path) => path.includes("outcome=difference"))).toBe(true));
    fireEvent.click(screen.getByRole("button", { name: "查看正式快照" }));
    expect(navigate).toHaveBeenCalledWith("/history/confirmation-1");
    fireEvent.click(screen.getByRole("button", { name: "查看旧版历史" }));
    expect(navigate).toHaveBeenCalledWith("/history/legacy");
  });

  it("renders the saved line result and history metadata read-only", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      expect(String(input)).toBe("/api/workspace/confirmations/confirmation-1");
      return response(detail);
    });
    const navigate = renderPage({ confirmationId: "confirmation-1" });

    expect(await screen.findByText("EGGS-12")).toBeTruthy();
    expect(screen.getByText("Supplier confirmed a short delivery.")).toBeTruthy();
    expect(screen.getByText("actor-1")).toBeTruthy();
    expect(screen.getByText("已确认的未核验维度")).toBeTruthy();
    expect(screen.getByText("确认时已知这些项目缺少可比较数据；它们没有被记为差异。")).toBeTruthy();
    expect(screen.getByText("Receive Note 通常不记录 GST，缺少可与 Invoice 税额比较的数据。")).toBeTruthy();
    expect(screen.getByText("已保存的实际差异")).toBeTruthy();
    expect(screen.getByRole("button", { name: "导出 CSV" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /认领|审批|修改/ })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "返回历史记录" }));
    expect(navigate).toHaveBeenCalledWith("/history");
  });
});
