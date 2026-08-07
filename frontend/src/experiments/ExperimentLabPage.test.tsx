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
      throw new Error(`Unexpected request: ${String(input)}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    expect(await screen.findByText("Admin access required.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Quality Lab" })).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(1);
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

    const baseline = await screen.findByLabelText("Baseline");
    const candidate = screen.getByLabelText("Candidate");
    expect(screen.queryByRole("option", { name: "run-incomplete" })).toBeNull();
    fireEvent.change(baseline, { target: { value: "run-a" } });
    fireEvent.change(candidate, { target: { value: "run-b" } });
    expect(screen.getAllByText("Not configured").length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: "Compare completed runs" }));
    expect(await screen.findByText("schema_valid_rate (hard)")).toBeTruthy();
    expect(screen.getByText("business_scenario: short delivery")).toBeTruthy();

    const classification = screen.getByLabelText("Classification");
    fireEvent.change(classification, { target: { value: "acceptable_variant" } });
    expect((screen.getByLabelText("Include in Gold") as HTMLInputElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(feedbackReads).toBeGreaterThan(1));
  });
});
