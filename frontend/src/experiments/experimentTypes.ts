export type FeedbackClassification =
  | "model_error"
  | "acceptable_variant"
  | "reviewer_correction_error"
  | "business_context_update";

export type ExperimentDefinition = {
  experiment_id: string;
  name: string;
  role: "baseline" | "candidate";
  normalizer_model: string;
  prompt_version: string;
  dataset_identity: { version: string; manifest_sha256: string };
};

export type ErrorSlice = {
  dimension: string;
  value: string;
  document_count: number;
  error_count: number;
};

export type EvaluationSummary = {
  document_count: number;
  schema_valid_rate: string;
  field_micro_accuracy: string;
  line_item_f1: string;
  evidence_coverage: string;
  average_cost_aud: string | null;
};

export type EvaluationRun = {
  run_id: string;
  experiment_id: string;
  status: "queued" | "running" | "completed" | "failed" | "cancelled";
  summary: EvaluationSummary | null;
  slices: ErrorSlice[];
};

export type PromotionCheck = {
  code: string;
  hard_gate: boolean;
  passed: boolean;
  reason: string;
  baseline_value: unknown;
  candidate_value: unknown;
  threshold: unknown;
};

export type PromotionDecision = {
  decision_id: string;
  outcome: "recommended" | "rejected" | "inconclusive";
  reasons: string[];
  checks: PromotionCheck[];
};

export type FeedbackCandidate = {
  candidate_id: string;
  field_path: string;
  old_value: unknown;
  new_value: unknown;
  document_type: string;
  normalizer_model: string;
  classification: FeedbackClassification | null;
  include_in_gold: boolean;
  confirmed_at: string | null;
};
