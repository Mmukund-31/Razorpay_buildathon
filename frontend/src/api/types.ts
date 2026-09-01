export interface DashboardMetrics {
  total_amount_at_risk: number;
  total_recoverable: number;
  total_recovered: number;
  recovery_rate: number;
  active_cases_count: number;
  actions_executed_count: number;
  actions_prevented_count: number;
  abstentions_count: number;
  recent_cases: RecoveryCaseSummary[];
}

export interface RecoveryCaseSummary {
  id: string;
  payment_id: string;
  status: string;
  amount: number;
  currency: string;
  selected_action: string | null;
  attempt_count: number;
  created_at: string;
  updated_at: string;
}

export interface RecoveryCaseListResponse {
  items: RecoveryCaseSummary[];
  total: number;
  page: number;
  page_size: number;
}

export interface RecoveryCaseDetail extends RecoveryCaseSummary {
  customer_id: string | null;
  max_attempts: number;
  recovery_window_expires_at: string | null;
  opportunity_id: string;
}

export interface PaymentContext {
  payment_id: string;
  razorpay_payment_id: string;
  amount: number;
  currency: string;
  status: string;
  failure_class: string | null;
  error_reason: string | null;
}

export interface AIDiagnosis {
  failure_class: string;
  diagnosis: string;
  confidence: number;
  recommended_action: string;
  reason_codes: string[];
  customer_action_required: boolean;
  communication_mode: string;
}

export interface CandidateAction {
  action_type: string;
  recovery_probability: number;
  expected_recovery: number;
  intervention_cost: number;
  risk_cost: number;
  expected_value: number;
}

export interface PolicyDecision {
  allowed: boolean;
  reason_codes: string[];
  policy_version: string;
  expected_value: number | null;
}

export interface ExecutionRecord {
  action_type: string;
  status: string;
  channel: string | null;
  external_reference: string | null;
  executed_at: string | null;
  result: Record<string, unknown> | null;
  consent_recorded: boolean;
}

export interface DecisionTrace {
  recovery_case_id: string;
  status: string;
  payment: PaymentContext;
  ml_score: number | null;
  ai_diagnosis: AIDiagnosis | null;
  candidates: CandidateAction[];
  selected_action: string | null;
  policy_decision: PolicyDecision | null;
  execution: ExecutionRecord | null;
  outcome: string | null;
  actual_recovered_amount: number | null;
}

export interface BenchmarkExperiment {
  id: string;
  name: string;
  baseline_type: string;
  dataset_ref: string | null;
  status: string;
  metrics: Record<string, number>;
}

export interface AuditLogEntry {
  id: string;
  correlation_id: string;
  entity_type: string;
  entity_id: string;
  event: string;
  actor: string;
  decision: string | null;
  reason: string | null;
  model_version: string | null;
  policy_version: string | null;
  details: Record<string, unknown> | null;
  created_at: string;
}
