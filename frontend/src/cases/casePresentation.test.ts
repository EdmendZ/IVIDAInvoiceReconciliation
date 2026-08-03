import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, api, type User } from "../api/client";
import {
  adminActions,
  availableSubmission,
  canCompleteClaim,
  canEditCase,
  canReassignCase,
  caseLineForItem,
  caseStatusLabel,
  queryForTab,
  resolutionLabel,
} from "./casePresentation";
import type {
  CaseItem,
  CaseLineResult,
  CaseStatus,
  ReconciliationCase,
  ResolutionType,
} from "./caseTypes";

const NOW = "2026-08-03T10:00:00Z";

function reviewer(userId: string): User {
  return { user_id: userId, username: userId, role: "reviewer" };
}

function admin(): User {
  return { user_id: "admin-a", username: "admin-a", role: "admin" };
}

function claimedCase(assigneeUserId: string): ReconciliationCase {
  return {
    case_id: "case-a",
    reconciliation_id: "reconciliation-a",
    status: "in_progress",
    assignee_user_id: assigneeUserId,
    revision: 2,
    created_by: "reviewer-origin",
    created_at: NOW,
    claimed_at: NOW,
    submitted_at: null,
    completed_at: null,
  };
}

function item(resolutionType: ResolutionType | null): CaseItem {
  return {
    item_id: `item-${resolutionType ?? "unresolved"}`,
    case_id: "case-a",
    item_type: "line",
    line_result_id: "line-a",
    resolution_type: resolutionType,
    resolution_note: resolutionType === null ? null : "Reviewed",
    resolved_by: resolutionType === null ? null : "reviewer-a",
    resolved_at: resolutionType === null ? null : NOW,
    updated_at: NOW,
  };
}

describe("case presentation", () => {
  it("maps queue tabs to stable API filters", () => {
    expect(queryForTab("unassigned", 1)).toBe(
      "assignment=unassigned&page=1&page_size=50",
    );
    expect(queryForTab("mine", 2)).toBe(
      "assignment=mine&page=2&page_size=50",
    );
    expect(queryForTab("admin-decisions", 1)).toContain(
      "status=pending_approval&status=pending_void",
    );
    expect(queryForTab("completed", 1)).toContain(
      "status=approved&status=voided",
    );
  });

  it("links a line Case Item to its business-readable reconciliation row", () => {
    const lineItem = {
      ...item(null),
      line_result_id: "line-result-a",
    };
    const lineResults: CaseLineResult[] = [
      {
        line_result_id: "line-result-a",
        line: {
          match_key: "SKU-001",
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
    ];

    expect(caseLineForItem(lineItem, lineResults)).toMatchObject({
      sku: "SKU-001",
      description: "Blue widget",
      quantity_difference: "-2",
    });
    expect(
      caseLineForItem(
        { ...lineItem, item_type: "purchase_order_conflict", line_result_id: null },
        lineResults,
      ),
    ).toBeNull();
  });

  it("does not complete a claim after its queue page has been left", () => {
    expect(canCompleteClaim(true, "case-a", "case-a")).toBe(true);
    expect(canCompleteClaim(false, "case-a", "case-a")).toBe(false);
    expect(canCompleteClaim(true, "case-a", "case-b")).toBe(false);
  });

  it("allows only the assigned reviewer to edit an in-progress case", () => {
    expect(canEditCase(claimedCase("reviewer-a"), reviewer("reviewer-a"))).toBe(true);
    expect(canEditCase(claimedCase("reviewer-a"), reviewer("reviewer-b"))).toBe(false);
    expect(canEditCase(claimedCase("reviewer-a"), admin())).toBe(false);
    expect(
      canEditCase(
        { ...claimedCase("reviewer-a"), status: "pending_approval" },
        reviewer("reviewer-a"),
      ),
    ).toBe(false);
  });

  it("derives approval and void submissions from all resolutions", () => {
    expect(availableSubmission([item("business_exception")])).toBe("approval");
    expect(
      availableSubmission([
        item("business_exception"),
        item("document_data_error"),
      ]),
    ).toBe("void");
    expect(availableSubmission([item("matching_error")])).toBe("void");
    expect(availableSubmission([item("waiting_for_documents")])).toBe(null);
    expect(availableSubmission([item(null)])).toBe(null);
    expect(availableSubmission([])).toBe(null);
  });

  it("shows admin actions only in matching pending states", () => {
    expect(
      adminActions(
        { ...claimedCase("reviewer-a"), status: "pending_approval" },
        admin(),
      ),
    ).toEqual(["approve", "return"]);
    expect(
      adminActions(
        { ...claimedCase("reviewer-a"), status: "pending_void" },
        admin(),
      ),
    ).toEqual(["void", "return"]);
    expect(
      adminActions(
        { ...claimedCase("reviewer-a"), status: "approved" },
        admin(),
      ),
    ).toEqual([]);
    expect(
      adminActions(
        { ...claimedCase("reviewer-a"), status: "pending_approval" },
        reviewer("reviewer-a"),
      ),
    ).toEqual([]);
  });

  it("allows reassignment only for assigned non-terminal Cases", () => {
    expect(canReassignCase(claimedCase("reviewer-a"), admin())).toBe(true);
    expect(
      canReassignCase(
        { ...claimedCase("reviewer-a"), assignee_user_id: null },
        admin(),
      ),
    ).toBe(false);
    expect(canReassignCase(claimedCase("reviewer-a"), reviewer("reviewer-a"))).toBe(
      false,
    );
    expect(
      canReassignCase(
        { ...claimedCase("reviewer-a"), status: "approved" },
        admin(),
      ),
    ).toBe(false);
  });

  it("labels every case status explicitly", () => {
    const expected: Array<[CaseStatus, string]> = [
      ["unassigned", "Unassigned"],
      ["in_progress", "In progress"],
      ["pending_approval", "Pending approval"],
      ["pending_void", "Pending void"],
      ["approved", "Approved"],
      ["voided", "Voided"],
    ];

    expect(expected.map(([status]) => caseStatusLabel(status))).toEqual(
      expected.map(([, label]) => label),
    );
  });

  it("labels every resolution explicitly", () => {
    const expected: Array<[ResolutionType, string]> = [
      ["business_exception", "Business exception"],
      ["document_data_error", "Document data error"],
      ["matching_error", "Matching error"],
      ["waiting_for_documents", "Waiting for documents"],
    ];

    expect(expected.map(([resolution]) => resolutionLabel(resolution))).toEqual(
      expected.map(([, label]) => label),
    );
  });
});

describe("API errors", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("preserves a structured backend error code", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: {
            code: "CASE_REVISION_CONFLICT",
            message: "Case has changed; refresh and retry",
          },
        }),
        {
          status: 409,
          headers: { "Content-Type": "application/json" },
        },
      ),
    );

    await expect(api("/api/reconciliation-cases/case-a")).rejects.toMatchObject({
      name: "Error",
      message: "Case has changed; refresh and retry",
      status: 409,
      code: "CASE_REVISION_CONFLICT",
    } satisfies Partial<ApiError>);
  });

  it("preserves legacy string details in an ApiError", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "Not found" }), {
        status: 404,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await expect(api("/api/missing")).rejects.toEqual(
      new ApiError("Not found", 404),
    );
  });

  it("falls back to an ApiError when the JSON error body is null", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(null), {
        status: 500,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await expect(api("/api/failure")).rejects.toEqual(
      new ApiError("Request failed (500)", 500),
    );
  });
});
