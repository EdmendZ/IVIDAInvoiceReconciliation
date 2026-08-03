import type { User } from "../api/client";
import type {
  CaseItem,
  CaseStatus,
  ReconciliationCase,
  ResolutionType,
} from "./caseTypes";

export type SubmissionType = "approval" | "void";

export function canEditCase(
  reconciliationCase: ReconciliationCase,
  user: User,
): boolean {
  return (
    reconciliationCase.status === "in_progress" &&
    user.role === "reviewer" &&
    reconciliationCase.assignee_user_id === user.user_id
  );
}

export function availableSubmission(
  items: readonly CaseItem[],
): SubmissionType | null {
  if (
    items.length === 0 ||
    items.some(
      (item) =>
        item.resolution_type === null ||
        item.resolution_type === "waiting_for_documents",
    )
  ) {
    return null;
  }

  if (
    items.some(
      (item) =>
        item.resolution_type === "document_data_error" ||
        item.resolution_type === "matching_error",
    )
  ) {
    return "void";
  }

  return items.every(
    (item) => item.resolution_type === "business_exception",
  )
    ? "approval"
    : null;
}

export function caseStatusLabel(status: CaseStatus): string {
  switch (status) {
    case "unassigned":
      return "Unassigned";
    case "in_progress":
      return "In progress";
    case "pending_approval":
      return "Pending approval";
    case "pending_void":
      return "Pending void";
    case "approved":
      return "Approved";
    case "voided":
      return "Voided";
    default:
      return assertNever(status);
  }
}

export function resolutionLabel(resolution: ResolutionType): string {
  switch (resolution) {
    case "business_exception":
      return "Business exception";
    case "document_data_error":
      return "Document data error";
    case "matching_error":
      return "Matching error";
    case "waiting_for_documents":
      return "Waiting for documents";
    default:
      return assertNever(resolution);
  }
}

function assertNever(value: never): never {
  throw new Error(`Unhandled value: ${String(value)}`);
}
