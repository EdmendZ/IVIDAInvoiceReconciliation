/** Types for the frozen /api/workspace JSON contract.
 *
 * Dates are ISO strings and financial values are decimal strings.  Keeping the
 * wire representation here prevents the browser from silently rounding money.
 */

export type DocumentType = "invoice" | "receive_note";
export type ProcessingStatus = "processing" | "ready" | "failed" | "cancelled" | "voided";
export type MatchStatus = "waiting_counterpart" | "needs_selection" | "selected";
export type ReviewStatus = "open" | "investigating" | "completed";
export type DisplayStatus =
  | "processing" | "failed" | "cancelled" | "voided"
  | "waiting_counterpart" | "needs_attention" | "awaiting_confirmation" | "completed";
export type SourceKind = "upload" | "taptouch";
export type SelectionOrigin = "automatic" | "manual";
export type RevisionOrigin = "extracted" | "manual" | "upstream";
export type Resolution = "matched" | "resolved_with_note";
export type WorkspaceOperation =
  | "edit" | "select" | "investigate" | "confirm" | "reopen" | "void" | "retry";
export type ActionType =
  | "uploaded" | "extracted" | "edited" | "selection_changed" | "investigating"
  | "confirmed" | "reopened" | "voided" | "source_updated" | "retry_requested";
export type MetricStatus = "equal" | "within_tolerance" | "different" | "unverified";
export type LineStatus = MetricStatus | "invoice_only" | "receive_only";
export type PreviewOutcome = "consistent" | "difference" | "blocked";
export type Coverage = "quantity_only" | "quantity_and_price" | "quantity_and_amount" | "full";
export type BlockingCode =
  | "EMPTY_ITEM_KEY" | "UNIT_UNVERIFIED" | "UNIT_CONFLICT" | "SUPPLIER_UNVERIFIED"
  | "SUPPLIER_CONFLICT" | "CURRENCY_CONFLICT" | "UNSUPPORTED_CURRENCY" | "SOURCE_VOIDED"
  | "VALIDATION_BLOCKED" | "DUPLICATE_INVOICE" | "RECEIVING_IN_USE";
export type CandidateReasonCode =
  | "PO_MATCH" | "PO_CONFLICT" | "SUPPLIER_MATCH" | "SUPPLIER_UNVERIFIED"
  | "SUPPLIER_CONFLICT" | "CURRENCY_MATCH" | "CURRENCY_CONFLICT" | "DATE_NEAR"
  | "DATE_MISSING" | "DATE_OUTSIDE_WINDOW" | "ITEM_OVERLAP" | "NO_ITEM_OVERLAP"
  | "RECEIVING_IN_USE" | "SOURCE_VOIDED";

export type WorkspaceErrorCode =
  | "INVALID_REQUEST" | "AUTH_REQUIRED" | "FORBIDDEN" | "DOCUMENT_NOT_FOUND"
  | "REVISION_CONFLICT" | "PREVIEW_STALE" | "SOURCE_REVIEW_REQUIRED" | "SOURCE_VOIDED"
  | "RECEIVING_IN_USE" | "IDEMPOTENCY_CONFLICT" | "INVALID_TRANSITION" | "LEGACY_READ_ONLY"
  | "VALIDATION_BLOCKED" | "UNRESOLVED_MATCH" | "UNVERIFIED_NOT_ACKNOWLEDGED"
  | "RESOLUTION_NOTE_REQUIRED" | "SUBJECT_CONFLICT" | "PARTIAL_ALLOCATION_UNSUPPORTED"
  | "DUPLICATE_INVOICE" | "INVALID_FILE" | "STORAGE_UNAVAILABLE" | "WORKSPACE_UNAVAILABLE"
  | "INTERNAL_ERROR";

export type Party = {
  name: string | null;
  business_number: string | null;
  address: string | null;
};

export type LineItem = {
  line_number: string | null;
  sku: string | null;
  description: string;
  quantity: string;
  unit: string | null;
  tax_code: string | null;
  unit_price: string | null;
  tax_amount: string | null;
  line_total: string | null;
};

export type BusinessDocument = {
  document_type: DocumentType;
  document_number: string;
  document_date: string | null;
  purchase_order_number: string | null;
  currency: string;
  supplier: Party | null;
  location: Party | null;
  subtotal: string | null;
  tax_total: string | null;
  total: string | null;
  items: LineItem[];
};
export type Invoice = BusinessDocument & { document_type: "invoice" };
export type ReceiveNote = BusinessDocument & { document_type: "receive_note" };
export type DocumentPayload = Invoice | ReceiveNote;

export type FieldEvidence = {
  field_path: string;
  value: string | null;
  page: number | null;
  source_text: string;
  block_id: string | null;
  table_id: string | null;
  row_index: number | null;
  confidence: string | null;
};
export type ValidationIssue = {
  rule_code: string;
  severity: "warning" | "blocking";
  field_path: string;
  message: string;
  measured_difference: string | null;
};

export type Tolerances = { quantity: string; unit_price: string; amount: string };
export type MetricComparison = {
  invoice_value: string | null;
  received_value: string | null;
  difference: string | null;
  status: MetricStatus;
  reason_code: string | null;
};
export type ReceiveLineReference = { document_id: string; line_index: number };
export type LineResult = {
  match_key: string;
  sku: string | null;
  description: string;
  invoice_unit: string | null;
  received_unit: string | null;
  quantity: MetricComparison;
  price: MetricComparison;
  amount: MetricComparison;
  status: LineStatus;
  reason_codes: string[];
  invoice_line_indexes: number[];
  receive_lines: ReceiveLineReference[];
};
export type PreviewSummary = { total_lines: number; different_lines: number; unverified_lines: number };
export type SubjectComparison = {
  supplier: "equal" | "unverified" | "conflict";
  currency: "equal" | "conflict";
  scope: "equal";
};
export type PreviewResult = {
  outcome: PreviewOutcome;
  coverage: Coverage;
  blocking_codes: BlockingCode[];
  unverified_dimensions: string[];
  lines: LineResult[];
  summary: PreviewSummary;
  subject: SubjectComparison;
};
export type RevisionView = {
  revision_id: string;
  document_id: string;
  sequence: number;
  origin: RevisionOrigin;
  payload: DocumentPayload;
  evidence: FieldEvidence[];
  validation_issues: ValidationIssue[];
  evidence_origin_revision_id: string | null;
  created_at: string;
};
export type Candidate = {
  document_id: string;
  revision_id: string;
  document_number: string;
  score: number;
  eligible: boolean;
  reason_codes: CandidateReasonCode[];
  source_kind: SourceKind;
  supplier_name: string | null;
  document_date: string | null;
  already_used: boolean;
};
export type MatchProposal = {
  status: MatchStatus;
  candidates: Candidate[];
  selected_document_ids: string[];
};
export type PreviewView = {
  preview_id: string;
  input_revision_ids: string[];
  scope_generation: number;
  rule_version: "ir-simple-rules-1";
  tolerances: Tolerances;
  input_sha256: string;
  result: PreviewResult;
  created_at: string;
};
export type ConfirmationView = {
  confirmation_id: string;
  preview_id: string;
  invoice_number: string;
  receive_note_numbers: string[];
  resolution: Resolution;
  note: string | null;
  acknowledged_unverified_dimensions: string[];
  result_snapshot: PreviewResult;
  rule_version: "ir-simple-rules-1";
  tolerances: Tolerances;
  input_revision_ids: string[];
  actor_id: string;
  created_at: string;
};
export type ActionView = {
  action_id: string;
  action: ActionType;
  actor_id: string | null;
  reason: string | null;
  old_revision: number | null;
  new_revision: number;
  confirmation_id: string | null;
  created_at: string;
};
export type DocumentSummary = {
  document_id: string;
  document_type: DocumentType;
  source_kind: SourceKind;
  revision: number;
  processing_status: ProcessingStatus;
  display_status: DisplayStatus;
  document_number: string | null;
  supplier_name: string | null;
  document_date: string | null;
  selected_document_ids: string[];
  source_changed: boolean;
  updated_at: string;
  error_code: string | null;
};
export type DocumentDetail = {
  document: DocumentSummary;
  review_status: ReviewStatus | null;
  match_status: MatchStatus;
  selection_origin: SelectionOrigin | null;
  selection_note: string | null;
  current_revision: RevisionView | null;
  candidates: Candidate[];
  selected_receivings: RevisionView[];
  preview: PreviewView | null;
  preview_stale: boolean;
  confirmation: ConfirmationView | null;
  actions: ActionView[];
  source_url_available: boolean;
};

export type PageQuery = { page?: number; page_size?: number };
export type DocumentQuery = PageQuery & {
  type?: DocumentType;
  status?: DisplayStatus[];
  q?: string | null;
};
export type DocumentPage = { items: DocumentSummary[]; page: number; page_size: number; total: number };
export type ActionPage = { items: ActionView[]; page: number; page_size: number; total: number };

export type UploadCommand = { document_type: DocumentType; filename: string; data: Blob };
export type RevisionCommand = { expected_revision: number };
export type ReasonCommand = RevisionCommand & { reason: string };
export type EditCommand = ReasonCommand & { document: DocumentPayload };
export type SelectionCommand = ReasonCommand & { receive_document_ids: string[] };
export type InvestigateCommand = RevisionCommand & { note: string };
export type ConfirmCommand = RevisionCommand & {
  preview_id: string;
  acknowledged_sources: true;
  acknowledged_unverified_dimensions: string[];
  resolution: Resolution;
  note?: string | null;
};
export type IntakeResponse = { document: DocumentSummary; task_id: string; run_id: string; duplicate: boolean };
export type ConfirmationResponse = { document: DocumentSummary; confirmation: ConfirmationView };
export type RetryResponse = { document: DocumentSummary; run_id: string };
export type WorkspaceMutationResponse = DocumentSummary | ConfirmationResponse | RetryResponse;
export type SourceFile = { filename: string; content_type: string; data: Blob };
export type RuntimeView = {
  enabled: boolean;
  worker_online: boolean;
  last_sync_at: string | null;
  preview_lag_seconds: number | null;
};
export type CachedResponse = { status: number; body: Record<string, unknown> };
export type SyncSummary = { changed_documents: number; scope_generation: number };
export type TickSummary = { synced: number; previews_saved: number; previews_discarded: number; errors: number };
export type WorkspaceErrorDetail = {
  code: WorkspaceErrorCode;
  message: string;
  document_id?: string;
  current_revision?: number;
};
export type WorkspaceErrorResponse = { detail: WorkspaceErrorDetail };

export type WorkspaceRequestOptions = { idempotencyKey?: string };
export type UploadDocumentInput = {
  file: Blob;
  document_type: DocumentType;
  filename?: string;
  idempotencyKey?: string;
};

export type WorkspaceScopeKey = { tenant_id: string; store_id: string };
export type ExtractionTask = {
  task_id: string;
  document_type: DocumentType;
  original_filename: string;
  content_type: string;
  size_bytes: number;
  sha256: string;
  storage_bucket: string;
  storage_object_key: string;
  purchase_order_hint: string | null;
  status: "uploaded" | "extracting" | "ready_for_review" | "approved" | "failed" | "cancelled";
  error_message: string | null;
  created_at: string;
  updated_at: string;
};
export type PreparedUpload = { task: ExtractionTask };
export type SourceMetadata = { filename: string; content_type: string; object_key: string };
export type PreviewInput = {
  invoice: RevisionView;
  receivings: RevisionView[];
  used_ids: string[];
  scope_generation: number;
  document_revision: number;
  manual_selection_ids: string[] | null;
};
