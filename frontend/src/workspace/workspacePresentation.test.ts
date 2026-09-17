import { describe, expect, it } from "vitest";
import { canConfirm, canEdit, canReopen, displayStatusLabel, metricStatusLabel, unverifiedSummary } from "./workspacePresentation";
import type { DocumentDetail, PreviewResult } from "./workspaceTypes";

const revision = {
  revision_id: "rev-1", document_id: "doc-1", sequence: 1, origin: "extracted" as const,
  payload: { document_type: "invoice" as const, document_number: "INV-1", document_date: null,
    purchase_order_number: null, currency: "AUD", supplier: null, location: null,
    subtotal: null, tax_total: null, total: null, items: [] }, evidence: [], validation_issues: [],
  evidence_origin_revision_id: null, created_at: "2026-09-16T00:00:00Z",
};
const result: PreviewResult = {
  outcome: "consistent", coverage: "quantity_only", blocking_codes: [],
  unverified_dimensions: ["price", "amount", "document_total", "tax"], lines: [],
  summary: { total_lines: 1, different_lines: 0, unverified_lines: 1 },
  subject: { supplier: "equal", currency: "equal", scope: "equal" },
};
function detail(overrides: Partial<DocumentDetail> = {}): DocumentDetail {
  return {
    document: { document_id: "doc-1", document_type: "invoice", source_kind: "upload", revision: 1,
      processing_status: "ready", display_status: "awaiting_confirmation", document_number: "INV-1",
      supplier_name: "English Foods Pty Ltd", document_date: null, selected_document_ids: ["rn-1"],
      source_changed: false, updated_at: "2026-09-16T00:00:00Z", error_code: null },
    review_status: "open", match_status: "selected", selection_origin: "automatic", selection_note: null,
    current_revision: revision, candidates: [], selected_receivings: [],
    selected_receiving_source_ids: [], related_invoices: [],
    preview: { preview_id: "preview-1", input_revision_ids: ["rev-1"], scope_generation: 1,
      rule_version: "ir-simple-rules-1", tolerances: { quantity: "0", unit_price: "0.01", amount: "0.02" },
      input_sha256: "hash", result, created_at: "2026-09-16T00:00:00Z" }, preview_stale: false,
    confirmation: null, actions: [], source_url_available: true, ...overrides,
  };
}

describe("workspace presentation", () => {
  it("labels statuses in Chinese while leaving business values to callers", () => {
    expect(displayStatusLabel("awaiting_confirmation")).toBe("待确认");
    expect(metricStatusLabel("within_tolerance")).toBe("容差内");
    expect(unverifiedSummary(result)).toBe("未核验：单价、金额、单据总额、税额");
  });

  it("only enables confirmation for a current selected invoice preview", () => {
    expect(canConfirm(detail())).toBe(true);
    expect(canConfirm(detail({ preview_stale: true }))).toBe(false);
    expect(canConfirm(detail({ preview: { ...detail().preview!, result: { ...result, outcome: "blocked", blocking_codes: ["UNIT_CONFLICT"] } } }))).toBe(false);
    expect(canConfirm(detail({ confirmation: { confirmation_id: "c", preview_id: "p", invoice_number: "INV-1", receive_note_numbers: [], resolution: "matched", note: null, acknowledged_unverified_dimensions: [], result_snapshot: result, rule_version: "ir-simple-rules-1", tolerances: { quantity: "0", unit_price: "0.01", amount: "0.02" }, input_revision_ids: [], actor_id: "a", created_at: "now" } }))).toBe(false);
    expect(canConfirm(detail({ document: { ...detail().document, document_type: "receive_note" } }))).toBe(false);
  });

  it("keeps upload invoices editable and completed invoices reopenable", () => {
    expect(canEdit(detail())).toBe(true);
    expect(canEdit(detail({
      document: { ...detail().document, document_type: "receive_note", display_status: "waiting_counterpart" },
    }))).toBe(true);
    expect(canEdit(detail({ document: { ...detail().document, source_kind: "taptouch" } }))).toBe(false);
    expect(canEdit(detail({
      document: { ...detail().document, document_type: "receive_note", display_status: "completed" },
    }))).toBe(false);
    expect(canReopen(detail({ document: { ...detail().document, display_status: "completed" }, review_status: "completed", confirmation: { confirmation_id: "c", preview_id: "p", invoice_number: "INV-1", receive_note_numbers: [], resolution: "matched", note: null, acknowledged_unverified_dimensions: [], result_snapshot: result, rule_version: "ir-simple-rules-1", tolerances: { quantity: "0", unit_price: "0.01", amount: "0.02" }, input_revision_ids: [], actor_id: "a", created_at: "now" } }))).toBe(true);
  });
});
