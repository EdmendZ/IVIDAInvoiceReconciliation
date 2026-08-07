import type { FeedbackClassification } from "./experimentTypes";

export function formatCost(value: string | null): string {
  return value === null ? "Not configured" : `AUD ${value}`;
}

export function formatPercent(value: string | null | undefined): string {
  return value == null ? "—" : `${(Number(value) * 100).toFixed(2)}%`;
}

export function canEnterGold(
  classification: FeedbackClassification | null,
): boolean {
  return classification === "model_error";
}

export function displayValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}
