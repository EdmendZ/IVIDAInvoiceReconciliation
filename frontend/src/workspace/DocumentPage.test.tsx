// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor, act } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DocumentPage } from "./DocumentPage";
import type { DocumentDetail, DocumentPayload, PreviewResult, RevisionView } from "./workspaceTypes";

function response(body: unknown, status = 200): Promise<Response> {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));
}

const payload: DocumentPayload = {
  document_type: "invoice",
  document_number: "INV-100",
  document_date: "2026-09-16",
  purchase_order_number: "PO-7",
  currency: "AUD",
  supplier: { name: "English Foods Pty Ltd", business_number: "ABN-1", address: "1 Long English Street" },
  location: null,
  subtotal: "50.00",
  tax_total: "5.00",
  total: "55.00",
  items: [{ line_number: "1", sku: "SKU-LONG", description: "Very long English product description <img src=x onerror=alert(1)>", quantity: "10", unit: "bag", tax_code: null, unit_price: "5.00", tax_amount: "5.00", line_total: "50.00" }],
};

function revision(documentId: string, documentPayload: DocumentPayload = payload): RevisionView {
  return {
    revision_id: `revision-${documentId}`,
    document_id: documentId,
    sequence: 1,
    origin: "extracted",
    payload: documentPayload,
    evidence: [{ field_path: "items[0].description", value: documentPayload.items[0]?.description ?? null, page: 1, source_text: "<script>alert('evidence')</script> English evidence", block_id: null, table_id: null, row_index: null, confidence: "0.90" }],
    validation_issues: [],
    evidence_origin_revision_id: null,
    created_at: "2026-09-16T00:00:00Z",
  };
}

const result: PreviewResult = {
  outcome: "difference",
  coverage: "quantity_only",
  blocking_codes: [],
  unverified_dimensions: ["price", "amount", "document_total", "tax"],
  lines: [{
    match_key: "sku:skulong|bag",
    sku: "SKU-LONG",
    description: payload.items[0]!.description,
    invoice_unit: "bag",
    received_unit: "bag",
    quantity: { invoice_value: "10", received_value: "8", difference: "2", status: "different", reason_code: "QUANTITY_DIFFERENT" },
    price: { invoice_value: "5.00", received_value: null, difference: null, status: "unverified", reason_code: "PRICE_MISSING" },
    amount: { invoice_value: "50.00", received_value: null, difference: null, status: "unverified", reason_code: "AMOUNT_MISSING" },
    status: "different",
    reason_codes: ["QUANTITY_DIFFERENT"],
    invoice_line_indexes: [0],
    receive_lines: [{ document_id: "rn-1", line_index: 0 }],
  }],
  summary: { total_lines: 1, different_lines: 1, unverified_lines: 1 },
  subject: { supplier: "equal", currency: "equal", scope: "equal" },
};

function invoiceDetail(overrides: Partial<DocumentDetail> = {}): DocumentDetail {
  const receivingPayload: DocumentPayload = { ...payload, document_type: "receive_note", document_number: "RN-1", total: null, tax_total: null, items: [{ ...payload.items[0]!, quantity: "8", unit_price: null, tax_amount: null, line_total: null }] };
  return {
    document: { document_id: "invoice-1", document_type: "invoice", source_kind: "upload", revision: 1, processing_status: "ready", display_status: "needs_attention", document_number: "INV-100", supplier_name: "English Foods Pty Ltd", document_date: "2026-09-16", selected_document_ids: ["rn-1"], source_changed: false, updated_at: "2026-09-16T00:00:00Z", error_code: null },
    review_status: "open",
    match_status: "selected",
    selection_origin: "automatic",
    selection_note: null,
    current_revision: revision("invoice-1"),
    candidates: [{ document_id: "rn-1", revision_id: "revision-rn-1", document_number: "RN-1", score: 80, eligible: true, reason_codes: ["PO_MATCH", "SUPPLIER_MATCH", "CURRENCY_MATCH"], source_kind: "upload", supplier_name: "English Foods Pty Ltd", document_date: "2026-09-16", already_used: false }],
    selected_receivings: [revision("rn-1", receivingPayload)],
    preview: { preview_id: "preview-1", input_revision_ids: ["revision-invoice-1", "revision-rn-1"], scope_generation: 1, rule_version: "ir-simple-rules-1", tolerances: { quantity: "0", unit_price: "0.01", amount: "0.02" }, input_sha256: "hash", result, created_at: "2026-09-16T00:00:00Z" },
    preview_stale: false,
    confirmation: null,
    actions: [{ action_id: "action-1", action: "extracted", actor_id: null, reason: null, old_revision: null, new_revision: 1, confirmation_id: null, created_at: "2026-09-16T00:00:00Z" }],
    source_url_available: false,
    ...overrides,
  };
}

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("DocumentPage", () => {
  it("renders English evidence as text and requires one acknowledged difference confirmation", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const path = String(input);
      if (path === "/api/workspace/documents/invoice-1" && !init?.method) return response(invoiceDetail());
      if (path.endsWith("/confirm")) return response({ document: { ...invoiceDetail().document, display_status: "completed" }, confirmation: {} }, 201);
      throw new Error(`Unexpected request: ${path}`);
    });
    render(<DocumentPage documentId="invoice-1" onNavigate={vi.fn()} />);

    expect(await screen.findByText("<script>alert('evidence')</script> English evidence")).toBeTruthy();
    expect(document.querySelector("script")).toBeNull();
    expect(screen.getByText("未核验维度")).toBeTruthy();
    expect(screen.getByText("单据总额")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "发现 1 行差异" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "高级 JSON 编辑" })).toBeNull();
    expect(screen.getByText("已自动关联 1 张收货单")).toBeTruthy();
    expect(screen.queryByLabelText("选择收货记录 RN-1")).toBeNull();
    const confirmButton = screen.getByRole("button", { name: "确认核对结果" }) as HTMLButtonElement;
    expect(confirmButton.disabled).toBe(true);

    fireEvent.change(screen.getByLabelText("差异处理说明"), { target: { value: "Supplier acknowledged the short delivery" } });
    fireEvent.click(screen.getByLabelText("我已核对发票、所选收货记录与未核验项目"));
    expect(confirmButton.disabled).toBe(false);
    fireEvent.click(confirmButton);

    await waitFor(() => expect(fetchMock.mock.calls.some(([input]) => String(input).endsWith("/confirm"))).toBe(true));
    const call = fetchMock.mock.calls.find(([input]) => String(input).endsWith("/confirm"))!;
    const sent = JSON.parse(String(call[1]?.body));
    expect(sent.resolution).toBe("resolved_with_note");
    expect(sent.acknowledged_sources).toBe(true);
    expect(sent.acknowledged_unverified_dimensions).toEqual(["price", "amount", "document_total", "tax"]);
  });

  it("refreshes after a 409 while retaining unsaved fields, selection and notes without replay", async () => {
    const newer = invoiceDetail({ document: { ...invoiceDetail().document, revision: 2 } });
    let reads = 0;
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const path = String(input);
      if (path === "/api/workspace/documents/invoice-1" && !init?.method) {
        reads += 1;
        return response(reads === 1 ? invoiceDetail() : newer);
      }
      if (path === "/api/workspace/documents/invoice-1" && init?.method === "PATCH") {
        return response({ detail: { code: "REVISION_CONFLICT", message: "单据已更新，请查看最新内容", document_id: "invoice-1", current_revision: 2 } }, 409);
      }
      throw new Error(`Unexpected request: ${path}`);
    });
    render(<DocumentPage allowAdvancedJson documentId="invoice-1" onNavigate={vi.fn()} />);
    await screen.findByRole("heading", { name: "INV-100" });

    fireEvent.click(screen.getByRole("button", { name: "高级 JSON 编辑" }));
    const json = screen.getByLabelText("结构化单据 JSON") as HTMLTextAreaElement;
    const changed = json.value.replace('"quantity": "10"', '"quantity": "12"');
    fireEvent.change(json, { target: { value: changed } });
    fireEvent.change(screen.getByLabelText("修改原因"), { target: { value: "Corrected from original PDF" } });
    fireEvent.click(screen.getByRole("button", { name: "修改关联" }));
    fireEvent.change(screen.getByLabelText("人工选择原因"), { target: { value: "Checked delivery evidence" } });
    fireEvent.change(screen.getByLabelText("待核实备注"), { target: { value: "Call supplier tomorrow" } });
    fireEvent.click(screen.getByLabelText("选择收货记录 RN-1"));
    fireEvent.click(screen.getByRole("button", { name: "显式保存字段" }));

    expect(await screen.findByText(/未保存的字段、选择和备注仍保留/)).toBeTruthy();
    expect((screen.getByLabelText("结构化单据 JSON") as HTMLTextAreaElement).value).toContain('"quantity": "12"');
    expect((screen.getByLabelText("人工选择原因") as HTMLInputElement).value).toBe("Checked delivery evidence");
    expect((screen.getByLabelText("待核实备注") as HTMLInputElement).value).toBe("Call supplier tomorrow");
    expect((screen.getByLabelText("选择收货记录 RN-1") as HTMLInputElement).checked).toBe(false);
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "PATCH")).toHaveLength(1);
  });

  it("fills the editor and automatic selection when processing becomes ready", async () => {
    let reads = 0;
    const processing = invoiceDetail({
      document: { ...invoiceDetail().document, document_number: null, supplier_name: null, processing_status: "processing", display_status: "processing", selected_document_ids: [] },
      match_status: "waiting_counterpart",
      current_revision: null,
      candidates: [],
      selected_receivings: [],
      preview: null,
    });
    const ready = invoiceDetail();
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      if (String(input) === "/api/workspace/documents/invoice-1") {
        reads += 1;
        return response(reads === 1 ? processing : ready);
      }
      throw new Error(`Unexpected request: ${String(input)}`);
    });
    render(<DocumentPage documentId="invoice-1" onNavigate={vi.fn()} />);

    expect(await screen.findByText("尚未提取编号")).toBeTruthy();
    fireEvent(document, new Event("visibilitychange"));
    await waitFor(() => expect((screen.getByLabelText("单据编号") as HTMLInputElement).value).toBe("INV-100"));
    expect(screen.getByText("已自动关联 1 张收货单")).toBeTruthy();
    expect(screen.queryByLabelText("选择收货记录 RN-1")).toBeNull();
    expect(reads).toBe(2);
  });

  it("keeps polling a waiting invoice until a later receive note produces a preview", async () => {
    let reads = 0;
    const waiting = invoiceDetail({
      document: { ...invoiceDetail().document, display_status: "waiting_counterpart", selected_document_ids: [] },
      match_status: "waiting_counterpart",
      selection_origin: null,
      candidates: [],
      selected_receivings: [],
      preview: null,
    });
    const ready = invoiceDetail();
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      if (String(input) === "/api/workspace/documents/invoice-1") {
        reads += 1;
        return response(reads === 1 ? waiting : ready);
      }
      throw new Error(`Unexpected request: ${String(input)}`);
    });
    render(<DocumentPage documentId="invoice-1" onNavigate={vi.fn()} />);

    expect(
      await screen.findByRole("heading", { name: "等待另一方单据" }),
    ).toBeTruthy();
    await waitFor(() => expect(screen.getByText("核对预览")).toBeTruthy(), { timeout: 4_500 });
    expect(reads).toBe(2);
  }, 8_000);

  it("refreshes a terminal page immediately after visibility resumes", async () => {
    let reads = 0;
    const completed = invoiceDetail({
      document: { ...invoiceDetail().document, display_status: "completed" },
      review_status: "completed",
    });
    const changed = invoiceDetail({
      document: { ...completed.document, source_changed: true },
      review_status: "completed",
    });
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      if (String(input) === "/api/workspace/documents/invoice-1") {
        reads += 1;
        return response(reads === 1 ? completed : changed);
      }
      throw new Error(`Unexpected request: ${String(input)}`);
    });
    render(<DocumentPage documentId="invoice-1" onNavigate={vi.fn()} />);

    await screen.findByRole("heading", { name: "INV-100" });
    fireEvent(document, new Event("visibilitychange"));
    expect(await screen.findByText("来源已更新")).toBeTruthy();
    expect(reads).toBe(2);
  });

  it("clears acknowledgement when the selected receiving changes", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      if (String(input) === "/api/workspace/documents/invoice-1") return response(invoiceDetail());
      throw new Error(`Unexpected request: ${String(input)}`);
    });
    render(<DocumentPage documentId="invoice-1" onNavigate={vi.fn()} />);

    await screen.findByRole("heading", { name: "INV-100" });
    const acknowledgement = screen.getByLabelText("我已核对发票、所选收货记录与未核验项目") as HTMLInputElement;
    fireEvent.click(acknowledgement);
    expect(acknowledgement.checked).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "修改关联" }));
    fireEvent.click(screen.getByLabelText("选择收货记录 RN-1"));
    await waitFor(() => expect(acknowledgement.checked).toBe(false));
  });

  it("ignores a stale response after switching to another document", async () => {
    let resolveOld!: (value: Response) => void;
    const oldResponse = new Promise<Response>((resolve) => { resolveOld = resolve; });
    const oldDetail = invoiceDetail({ document: { ...invoiceDetail().document, document_id: "old", document_number: "OLD-1" } });
    const newDetail = invoiceDetail({ document: { ...invoiceDetail().document, document_id: "new", document_number: "NEW-1" } });
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const path = String(input);
      if (path === "/api/workspace/documents/old") return oldResponse;
      if (path === "/api/workspace/documents/new") return response(newDetail);
      throw new Error(`Unexpected request: ${path}`);
    });
    const view = render(<DocumentPage documentId="old" onNavigate={vi.fn()} />);
    view.rerender(<DocumentPage documentId="new" onNavigate={vi.fn()} />);
    expect(await screen.findByRole("heading", { name: "NEW-1" })).toBeTruthy();
    await act(async () => { resolveOld(await response(oldDetail)); await Promise.resolve(); });
    await waitFor(() => expect(screen.getByRole("heading", { name: "NEW-1" })).toBeTruthy());
    expect(screen.queryByRole("heading", { name: "OLD-1" })).toBeNull();
  });

  it("keeps an authoritative receive note read-only and offers no confirmation button", async () => {
    const receivePayload: DocumentPayload = { ...payload, document_type: "receive_note", document_number: "RN-UPSTREAM" };
    const receiveDetail = invoiceDetail({
      document: { ...invoiceDetail().document, document_id: "rn-upstream", document_type: "receive_note", source_kind: "taptouch", display_status: "waiting_counterpart", document_number: "RN-UPSTREAM", selected_document_ids: [] },
      review_status: null,
      match_status: "waiting_counterpart",
      selection_origin: null,
      current_revision: revision("rn-upstream", receivePayload),
      candidates: [], selected_receivings: [], preview: null,
    });
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      if (String(input) === "/api/workspace/documents/rn-upstream") return response(receiveDetail);
      throw new Error(`Unexpected request: ${String(input)}`);
    });
    render(<DocumentPage documentId="rn-upstream" onNavigate={vi.fn()} />);

    expect(await screen.findByText("RN-UPSTREAM")).toBeTruthy();
    expect(screen.getByText("上游权威记录，只读")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "显式保存字段" })).toBeNull();
    expect(screen.queryByRole("button", { name: "确认核对结果" })).toBeNull();
    expect((screen.getByLabelText("单据编号") as HTMLInputElement).readOnly).toBe(true);
  });
});
