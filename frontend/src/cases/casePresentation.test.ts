import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, api, type User } from "../api/client";
import {
  availableSubmission,
  canEditCase,
  caseStatusLabel,
  queryForTab,
  resolutionLabel,
} from "./casePresentation";
import type {
  CaseItem,
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
});
