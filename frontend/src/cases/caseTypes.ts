export type CaseStatus =
  | "unassigned"
  | "in_progress"
  | "pending_approval"
  | "pending_void"
  | "approved"
  | "voided";

export type ResolutionType =
  | "business_exception"
  | "document_data_error"
  | "matching_error"
  | "waiting_for_documents";

export type CaseItemType =
  | "line"
  | "purchase_order_conflict"
  | "currency_conflict";

export type CaseActionType =
  | "created"
  | "claimed"
  | "reassigned"
  | "resolution_changed"
  | "submitted_for_approval"
  | "submitted_for_void"
  | "returned"
  | "approved"
  | "voided";

export type ReconciliationCase = {
  case_id: string;
  reconciliation_id: string;
  status: CaseStatus;
  assignee_user_id: string | null;
  revision: number;
  created_by: string;
  created_at: string;
  claimed_at: string | null;
  submitted_at: string | null;
  completed_at: string | null;
};

export type CaseItem = {
  item_id: string;
  case_id: string;
  item_type: CaseItemType;
  line_result_id: string | null;
  resolution_type: ResolutionType | null;
  resolution_note: string | null;
  resolved_by: string | null;
  resolved_at: string | null;
  updated_at: string;
};

export type CaseAction = {
  action_id: string;
  case_id: string;
  item_id: string | null;
  actor_user_id: string;
  action: CaseActionType;
  old_value: unknown;
  new_value: unknown;
  reason: string | null;
  created_at: string;
};

export type CaseSummary = {
  case: ReconciliationCase;
  invoice_number: string;
  receive_note_numbers: string[];
  actionable_count: number;
  assignee_username: string | null;
};

export type CaseActionView = {
  action: CaseAction;
  actor_username: string;
};

export type ReconciliationRecord = {
  reconciliation_id: string;
  invoice_version_id: string;
  receive_note_version_ids: string[];
  created_by: string;
  created_at: string;
  result: {
    invoice_number: string;
    receive_note_numbers: string[];
    purchase_order_match: boolean | null;
    currency_match: boolean;
    summary: {
      total_lines: number;
      exact_lines: number;
      tolerance_lines: number;
      mismatch_lines: number;
      invoice_only_lines: number;
      receive_note_only_lines: number;
      requires_review: boolean;
    };
    lines: Array<{
      match_key: string;
      sku: string | null;
      description: string;
      invoice_quantity: string;
      received_quantity: string;
      quantity_difference: string;
      invoice_unit_price: string | null;
      received_unit_price: string | null;
      unit_price_difference: string | null;
      invoice_amount: string | null;
      received_amount: string | null;
      amount_difference: string | null;
      status: string;
      reasons: string[];
    }>;
  };
};

export type CaseDetail = {
  case: ReconciliationCase;
  items: CaseItem[];
  actions: CaseActionView[];
  reconciliation: ReconciliationRecord;
};

export type CasePage = {
  items: CaseSummary[];
  page: number;
  page_size: number;
  total: number;
};
