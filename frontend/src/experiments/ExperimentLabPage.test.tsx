// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ExperimentLabPage } from "./ExperimentLabPage";
import { App } from "../app/App";

const definitions = [
  { experiment_id: "definition-a", name: "baseline", role: "baseline", normalizer_model: "model-a", prompt_version: "p1", dataset_identity: { version: "1", manifest_sha256: "a" } },
  { experiment_id: "definition-b", name: "candidate", role: "candidate", normalizer_model: "model-b", prompt_version: "p2", dataset_identity: { version: "1", manifest_sha256: "a" } },
];
const summary = { document_count: 2, schema_valid_rate: "1", field_micro_accuracy: "0.98", line_item_f1: "0.97", evidence_coverage: "0.96", average_cost_aud: null };
const runs = [
  { run_id: "run-a", experiment_id: "definition-a", status: "completed", summary, slices: [{ dimension: "error_type", value: "schema_failure", document_count: 1, error_count: 1 }] },
  { run_id: "run-b", experiment_id: "definition-b", status: "completed", summary, slices: [{ dimension: "business_scenario", value: "short delivery", document_count: 1, error_count: 1 }] },
  { run_id: "run-incomplete", experiment_id: "definition-b", status: "running", summary: null, slices: [] },
];
const feedback = [{ candidate_id: "feedback-1", field_path: "supplier.name", old_value: "Old", new_value: "New", document_type: "invoice", normalizer_model: "model-b", classification: null, include_in_gold: false, confirmed_at: null }];

function response(body: unknown) {
  return Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } }));
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><ExperimentLabPage /></QueryClientProvider>);
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("ExperimentLabPage", () => {
  it("denies a reviewer visiting /lab without experiment requests", async () => {
    window.history.replaceState({}, "", "/lab");
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      if (String(input) === "/api/auth/me") {
        return response({ user_id: "reviewer-1", username: "reviewer", role: "reviewer" });
      }
      if (String(input) === "/api/workspace/runtime") {
        return response({ enabled: true, worker_online: true, last_sync_at: null, preview_lag_seconds: 0 });
      }
      throw new Error(`Unexpected request: ${String(input)}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    expect(await screen.findByText("需要管理员权限。")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "质量评测" })).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("compares only completed runs and refreshes governed feedback", async () => {
    let feedbackReads = 0;
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/experiments") return response(definitions);
      if (path === "/api/experiment-runs") return response(runs);
      if (path.startsWith("/api/feedback-candidates?") && !init?.method) {
        feedbackReads += 1;
        return response(feedback);
      }
      if (path === "/api/promotion-decisions") return response({ decision_id: "decision-1", outcome: "recommended", reasons: [], checks: [{ code: "schema_valid_rate", hard_gate: true, passed: true, reason: "meets floor", baseline_value: "1", candidate_value: "1", threshold: "1" }] });
      if (path.endsWith("/confirm")) return response({ ...feedback[0], classification: "acceptable_variant", confirmed_at: "2026-08-07T00:00:00Z" });
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderPage();

    const baseline = await screen.findByLabelText("基线");
    const candidate = screen.getByLabelText("候选方案");
    expect(screen.queryByRole("option", { name: "run-incomplete" })).toBeNull();
    fireEvent.change(baseline, { target: { value: "run-a" } });
    fireEvent.change(candidate, { target: { value: "run-b" } });
    expect(screen.getAllByText("未配置").length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: "比较已完成的评测" }));
    expect(await screen.findByText("结构校验通过率（硬性要求）")).toBeTruthy();
    expect(screen.getByText("业务场景: short delivery")).toBeTruthy();

    const classification = screen.getByLabelText("分类");
    fireEvent.change(classification, { target: { value: "acceptable_variant" } });
    expect((screen.getByLabelText("纳入标准答案集") as HTMLInputElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "确认" }));
    await waitFor(() => expect(feedbackReads).toBeGreaterThan(1));
  });
});
