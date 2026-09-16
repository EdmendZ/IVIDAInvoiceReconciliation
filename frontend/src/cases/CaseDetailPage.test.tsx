// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { User } from "../api/client";
import { CaseDetailPage } from "./CaseDetailPage";
import type { CaseDetail, ResolutionType } from "./caseTypes";

const NOW = "2026-08-03T10:00:00Z";
const REVIEWER: User = {
  user_id: "reviewer-a",
  username: "alice",
  role: "reviewer",
};
const ADMIN: User = {
  user_id: "admin-a",
  username: "admin",
  role: "admin",
};

function detail(
  overrides: Partial<CaseDetail["case"]> = {},
  resolutionType: ResolutionType | null = null,
): CaseDetail {
  return {
    case: {
      case_id: "case-a",
      reconciliation_id: "reconciliation-a",
      status: "in_progress",
      assignee_user_id: REVIEWER.user_id,
      revision: 2,
      created_by: "reviewer-origin",
      created_at: NOW,
      claimed_at: NOW,
      submitted_at: null,
      completed_at: null,
      ...overrides,
    },
    assignee_username: "alice",
    items: [
      {
        item_id: "item-a",
        case_id: "case-a",
        item_type: "line",
        line_result_id: "line-a",
        resolution_type: resolutionType,
        resolution_note: resolutionType ? "Previously reviewed" : null,
        resolved_by: resolutionType ? REVIEWER.user_id : null,
        resolved_at: resolutionType ? NOW : null,
        updated_at: NOW,
      },
    ],
    actions: [
      {
        actor_username: "system-user",
        action: {
          action_id: "action-a",
          case_id: "case-a",
          item_id: null,
          actor_user_id: "reviewer-origin",
          action: "created",
          old_value: null,
          new_value: { status: "unassigned" },
          reason: null,
          created_at: NOW,
        },
      },
    ],
    reconciliation: {
      reconciliation_id: "reconciliation-a",
      invoice_version_id: "invoice-version-a",
      receive_note_version_ids: ["note-version-a"],
      created_by: "reviewer-origin",
      created_at: NOW,
      result: {
        invoice_number: "INV-100",
        receive_note_numbers: ["RN-100"],
        purchase_order_match: false,
        currency_match: true,
        summary: {
          total_lines: 2,
          exact_lines: 1,
          tolerance_lines: 0,
          mismatch_lines: 1,
          invoice_only_lines: 0,
          receive_note_only_lines: 0,
          requires_review: true,
        },
        lines: [
          {
            match_key: "sku:sku001",
            sku: "SKU-001",
            description: "Blue widget",
            invoice_quantity: "10",
            received_quantity: "8",
            quantity_difference: "-2",
            invoice_unit_price: "4.50",
            received_unit_price: "4.50",
            unit_price_difference: "0",
            invoice_amount: "45",
            received_amount: "36",
            amount_difference: "-9",
            status: "mismatch",
            reasons: ["quantity_difference"],
          },
          {
            match_key: "sku:sku002",
            sku: "SKU-002",
            description: "Green widget",
            invoice_quantity: "1",
            received_quantity: "1",
            quantity_difference: "0",
            invoice_unit_price: "2",
            received_unit_price: "2",
            unit_price_difference: "0",
            invoice_amount: "2",
            received_amount: "2",
            amount_difference: "0",
            status: "exact",
            reasons: [],
          },
        ],
      },
    },
    line_results: [
      {
        line_result_id: "line-a",
        line: {
          match_key: "sku:sku001",
          sku: "SKU-001",
          description: "Blue widget",
          invoice_quantity: "10",
          received_quantity: "8",
          quantity_difference: "-2",
          invoice_unit_price: "4.50",
          received_unit_price: "4.50",
          unit_price_difference: "0",
          invoice_amount: "45",
          received_amount: "36",
          amount_difference: "-9",
          status: "mismatch",
          reasons: ["quantity_difference"],
        },
      },
    ],
  };
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function renderPage(user = REVIEWER) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <CaseDetailPage caseId="case-a" user={user} onNavigate={vi.fn()} />
    </QueryClientProvider>,
  );
  return queryClient;
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("CaseDetailPage reviewer workflow", () => {
  it("separates actionable differences from immutable exact and tolerance lines", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(jsonResponse(detail()));
    renderPage();

    expect(await screen.findByText("INV-100")).toBeTruthy();
    const actionableSection = screen
      .getByRole("heading", { name: "差异项" })
      .closest("section");
    expect(actionableSection).not.toBeNull();
    expect(
      within(actionableSection!).getByText("发票单价"),
    ).toBeTruthy();
    const readOnlySection = screen
      .getByRole("heading", { name: "完全匹配与容差内明细" })
      .closest("section");
    expect(readOnlySection).not.toBeNull();
    expect(within(readOnlySection!).getByText("SKU-002")).toBeTruthy();
    expect(within(readOnlySection!).queryByText("SKU-001")).toBeNull();
  });

  it("saves one assigned reviewer's resolution with the current revision", async () => {
    const updated = detail({ revision: 3 }, "business_exception");
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse(detail()))
      .mockResolvedValueOnce(jsonResponse(updated));

    renderPage();

    fireEvent.change(await screen.findByLabelText("处置结论"), {
      target: { value: "business_exception" },
    });
    fireEvent.change(screen.getByLabelText("处置说明"), {
      target: { value: "  Supplier accepted short delivery  " },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存处置结果" }));

    await screen.findByText(/修订版本 3/);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[1]).toEqual([
      "/api/reconciliation-cases/case-a/items/item-a/resolution",
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify({
          resolution_type: "business_exception",
          note: "Supplier accepted short delivery",
          expected_revision: 2,
        }),
      }),
    ]);
  });

  it("submits only the approval transition supported by completed items", async () => {
    const updated = detail(
      { revision: 3, status: "pending_approval", submitted_at: NOW },
      "business_exception",
    );
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse(detail({}, "business_exception")))
      .mockResolvedValueOnce(jsonResponse(updated));

    renderPage();

    fireEvent.click(
      await screen.findByRole("button", { name: "提交审批" }),
    );

    await screen.findByText("待审批");
    expect(
      screen.queryByRole("button", { name: "申请作废" }),
    ).toBeNull();
    expect(fetchMock.mock.calls[1]).toEqual([
      "/api/reconciliation-cases/case-a/submit-approval",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ expected_revision: 2 }),
      }),
    ]);
  });

  it("explains why unresolved and waiting items block submission", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(jsonResponse(detail()));
    renderPage();

    expect(
      await screen.findByText(
        "请先完成所有差异项的处置，再提交决定。",
      ),
    ).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: /提交审批|申请作废/ }),
    ).toBeNull();

    cleanup();
    vi.restoreAllMocks();
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      jsonResponse(detail({}, "waiting_for_documents")),
    );
    renderPage();
    expect(
      await screen.findByText(
        "请先补齐所需单据并完成处置，再提交处理单。",
      ),
    ).toBeTruthy();
  });

  it("submits document and matching errors only for void", async () => {
    const updated = detail(
      { revision: 3, status: "pending_void", submitted_at: NOW },
      "document_data_error",
    );
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse(detail({}, "document_data_error")))
      .mockResolvedValueOnce(jsonResponse(updated));
    renderPage();

    fireEvent.click(
      await screen.findByRole("button", { name: "申请作废" }),
    );

    await screen.findByText("待作废审批");
    expect(
      screen.queryByRole("button", { name: "提交审批" }),
    ).toBeNull();
    expect(fetchMock.mock.calls[1][0]).toBe(
      "/api/reconciliation-cases/case-a/submit-void",
    );
  });

  it("loads the latest revision after a conflict without replaying or losing draft text", async () => {
    const latest = detail({ revision: 3 });
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse(detail()))
      .mockResolvedValueOnce(
        jsonResponse(
          {
            detail: {
              code: "CASE_REVISION_CONFLICT",
              message: "Case revision did not match",
            },
          },
          409,
        ),
      )
      .mockResolvedValueOnce(jsonResponse(latest));
    renderPage();

    fireEvent.change(await screen.findByLabelText("处置结论"), {
      target: { value: "business_exception" },
    });
    const note = screen.getByLabelText("处置说明") as HTMLTextAreaElement;
    fireEvent.change(note, { target: { value: "My unsaved explanation" } });
    fireEvent.click(screen.getByRole("button", { name: "保存处置结果" }));

    expect(
      await screen.findByText(
        "此处理单已被更新，现已加载最新版本，请重新确认。",
      ),
    ).toBeTruthy();
    await screen.findByText(/修订版本 3/);
    expect(note.value).toBe("My unsaved explanation");
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it.each([
    ["CASE_TERMINAL", { status: "approved" as const, completed_at: NOW }],
    ["CASE_INVALID_TRANSITION", { status: "pending_approval" as const }],
    ["CASE_ASSIGNEE_REQUIRED", { assignee_user_id: "reviewer-b" }],
  ])("refreshes detail after stale workflow error %s", async (code, overrides) => {
    const latest = detail({ revision: 3, ...overrides }, "business_exception");
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        jsonResponse(detail({}, "business_exception")),
      )
      .mockResolvedValueOnce(
        jsonResponse(
          { detail: { code, message: "The Case changed" } },
          code === "CASE_ASSIGNEE_REQUIRED" ? 403 : 409,
        ),
      )
      .mockResolvedValueOnce(jsonResponse(latest));
    renderPage();

    fireEvent.click(
      await screen.findByRole("button", { name: "提交审批" }),
    );

    expect(
      await screen.findByText(
        "此处理单已被更新，现已加载最新版本，请重新确认。",
      ),
    ).toBeTruthy();
    await screen.findByText(/修订版本 3/);
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });
});

describe("CaseDetailPage admin workflow", () => {
  it("loads active reviewers and requires a reason before reassignment", async () => {
    const updated = detail({ revision: 3, assignee_user_id: "reviewer-b" });
    updated.assignee_username = "bob";
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(
      async (input, init) => {
        if (input === "/api/reconciliation-cases/assignees") {
          return jsonResponse([
            { user_id: "reviewer-a", username: "alice" },
            { user_id: "reviewer-b", username: "bob" },
          ]);
        }
        if (init?.method === "POST") return jsonResponse(updated);
        return jsonResponse(detail());
      },
    );
    renderPage(ADMIN);

    await screen.findByRole("option", { name: "bob" });
    fireEvent.change(screen.getByLabelText("审核员"), {
      target: { value: "reviewer-b" },
    });
    const reassign = screen.getByRole("button", { name: "重新分派" });
    expect((reassign as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("重新分派原因"), {
      target: { value: "  Balance the review queue  " },
    });
    await waitFor(() =>
      expect((reassign as HTMLButtonElement).disabled).toBe(false),
    );
    fireEvent.click(reassign);

    await screen.findByText(/修订版本 3/);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/reconciliation-cases/case-a/reassign",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          assignee_user_id: "reviewer-b",
          reason: "Balance the review queue",
          expected_revision: 2,
        }),
      }),
    );
  });

  it("approves only a pending approval Case with its current revision", async () => {
    const initial = detail({ status: "pending_approval" }, "business_exception");
    const approved = detail(
      { status: "approved", revision: 3, completed_at: NOW },
      "business_exception",
    );
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(
      async (input, init) => {
        if (input === "/api/reconciliation-cases/assignees") {
          return jsonResponse([]);
        }
        if (init?.method === "POST") return jsonResponse(approved);
        return jsonResponse(initial);
      },
    );
    renderPage(ADMIN);

    const approve = await screen.findByRole("button", { name: "批准处理单" });
    expect(screen.queryByRole("button", { name: "作废处理单" })).toBeNull();
    expect(screen.getByRole("button", { name: "退回处理单" })).toBeTruthy();
    fireEvent.click(approve);

    await screen.findByText("已批准");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/reconciliation-cases/case-a/approve",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ expected_revision: 2 }),
      }),
    );
  });

  it("voids only a pending void Case", async () => {
    const initial = detail({ status: "pending_void" }, "document_data_error");
    const voided = detail(
      { status: "voided", revision: 3, completed_at: NOW },
      "document_data_error",
    );
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(
      async (input, init) => {
        if (input === "/api/reconciliation-cases/assignees") {
          return jsonResponse([]);
        }
        if (init?.method === "POST") return jsonResponse(voided);
        return jsonResponse(initial);
      },
    );
    renderPage(ADMIN);

    const voidCase = await screen.findByRole("button", { name: "作废处理单" });
    expect(screen.queryByRole("button", { name: "批准处理单" })).toBeNull();
    fireEvent.click(voidCase);

    await screen.findByText("已作废");
    expect(fetchMock.mock.calls.some(([path]) =>
      path === "/api/reconciliation-cases/case-a/void",
    )).toBe(true);
  });

  it("requires and sends an explanatory reason when returning a Case", async () => {
    const initial = detail({ status: "pending_approval" }, "business_exception");
    const returned = detail(
      { status: "in_progress", revision: 3 },
      "business_exception",
    );
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(
      async (input, init) => {
        if (input === "/api/reconciliation-cases/assignees") {
          return jsonResponse([]);
        }
        if (init?.method === "POST") return jsonResponse(returned);
        return jsonResponse(initial);
      },
    );
    renderPage(ADMIN);

    fireEvent.click(await screen.findByRole("button", { name: "退回处理单" }));
    const confirm = screen.getByRole("button", { name: "确认退回" });
    expect((confirm as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("退回原因"), {
      target: { value: "  Need supplier evidence  " },
    });
    await waitFor(() =>
      expect((confirm as HTMLButtonElement).disabled).toBe(false),
    );
    fireEvent.click(confirm);

    await screen.findByText("处理中");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/reconciliation-cases/case-a/return",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          reason: "Need supplier evidence",
          expected_revision: 2,
        }),
      }),
    );
  });
});

describe("CaseDetailPage immutable detail", () => {
  it("keeps terminal Cases read-only and exports the saved reconciliation CSV", async () => {
    const terminal = detail(
      { status: "approved", revision: 4, completed_at: NOW },
      "business_exception",
    );
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(
      async (input) => {
        if (input === "/api/reconciliations/reconciliation-a/export.csv") {
          return new Response("invoice,receive_note\nINV-100,RN-100", {
            headers: {
              "Content-Disposition": 'attachment; filename="reconciliation.csv"',
            },
          });
        }
        return jsonResponse(terminal);
      },
    );
    const createObjectURL = vi.fn(() => "blob:reconciliation");
    const revokeObjectURL = vi.fn();
    Object.defineProperties(URL, {
      createObjectURL: { configurable: true, value: createObjectURL },
      revokeObjectURL: { configurable: true, value: revokeObjectURL },
    });
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => undefined);
    renderPage();

    expect(await screen.findByText("已批准")).toBeTruthy();
    expect(screen.queryByLabelText("处置结论")).toBeNull();
    expect(screen.queryByRole("button", { name: "重新分派" })).toBeNull();
    expect(screen.getByText("采购订单号").parentElement?.textContent).toContain(
      "冲突",
    );
    expect(screen.getByText("币种").parentElement?.textContent).toContain(
      "一致",
    );
    fireEvent.click(screen.getByRole("button", { name: "导出 CSV" }));

    await waitFor(() => expect(click).toHaveBeenCalledTimes(1));
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/reconciliations/reconciliation-a/export.csv",
      { credentials: "include" },
    );
    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:reconciliation");
  });
});
