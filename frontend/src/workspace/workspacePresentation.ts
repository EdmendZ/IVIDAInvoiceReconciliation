import { label } from "../i18n";
import type { DocumentDetail, DisplayStatus, MetricStatus, PreviewResult } from "./workspaceTypes";

export function displayStatusLabel(status: DisplayStatus): string {
  return label(status);
}

export function metricStatusLabel(status: MetricStatus): string {
  return label(status);
}

/** A confirmation is a user acknowledgement of the current server preview.
 * This is only a conservative UI affordance; the server rechecks every rule. */
export function canConfirm(detail: DocumentDetail): boolean {
  const summary = detail.document;
  const preview = detail.preview;
  return (
    summary.document_type === "invoice" &&
    summary.processing_status === "ready" &&
    summary.display_status !== "completed" &&
    summary.display_status !== "voided" &&
    detail.review_status !== "completed" &&
    detail.match_status === "selected" &&
    detail.current_revision !== null &&
    preview !== null &&
    !detail.preview_stale &&
    preview.result.outcome !== "blocked" &&
    preview.result.blocking_codes.length === 0 &&
    detail.confirmation === null
  );
}

export function canEdit(detail: DocumentDetail): boolean {
  const summary = detail.document;
  return (
    summary.source_kind === "upload" &&
    summary.processing_status === "ready" &&
    summary.display_status !== "completed" &&
    summary.display_status !== "voided" &&
    detail.review_status !== "completed" &&
    detail.current_revision !== null &&
    detail.confirmation === null
  );
}

export function canReopen(detail: DocumentDetail): boolean {
  return (
    detail.document.document_type === "invoice" &&
    detail.document.display_status === "completed" &&
    detail.document.processing_status === "ready" &&
    detail.confirmation !== null
  );
}

export function unverifiedSummary(result: PreviewResult): string {
  const dimensions = result.unverified_dimensions.map((dimension) => label(dimension));
  return dimensions.length > 0
    ? `未核验：${dimensions.join("、")}`
    : "未发现未核验维度";
}
