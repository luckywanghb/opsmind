export type PrimaryIntent =
  | "SYSTEM_OPERATION"
  | "BUSINESS_RULE"
  | "ACCESS_ISSUE"
  | "WORKFLOW_ISSUE"
  | "DATA_ISSUE"
  | "OTHER";

export type RequestType =
  | "HOW_TO"
  | "EXPLAIN"
  | "DIAGNOSE"
  | "CHECK_STATUS"
  | "EXECUTE_CHANGE"
  | "CONTINUE_CASE"
  | "CONFIRM_RESOLVED"
  | "OTHER";

export type RiskSignal =
  | "NONE"
  | "PRIVILEGED_CHANGE"
  | "BROAD_OUTAGE"
  | "SECURITY_SUSPECTED"
  | "DESTRUCTIVE_OPERATION";

export type AgentAction =
  | "ASK_USER"
  | "SEARCH"
  | "REPLY"
  | "TRANSFER_HUMAN"
  | "END_CONVERSATION";

export type ModelTask =
  | "REQUEST_UNDERSTANDING"
  | "ACTION_DECISION"
  | "TOOL_SELECTION"
  | "TOOL_RESULT_REVIEW"
  | "CLARIFICATION"
  | "RESPONSE_GENERATION"
  | "HANDOFF_GENERATION";
export type ModelProfile = "CHEAP" | "STRONG" | "FALLBACK";

export interface ChatRequest {
  message: string;
  thread_id?: string;
  source_context: { channel: "web-demo"; user_id?: string; site_id?: string };
}

export interface RequestUnderstanding {
  primary_intent: PrimaryIntent;
  request_type: RequestType;
  symptom: string | null;
  entities: Record<string, unknown>;
  risk_signal: RiskSignal;
  uncertainty: string | null;
}

export interface ActionDecision {
  action: AgentAction;
  goal: string;
  rationale: string;
}

export interface TraceEntry {
  node: string;
  task: ModelTask;
  profile: ModelProfile | "HARNESS";
  status: "completed" | "failed" | "blocked";
  summary: string;
}

export interface ChatEvidence {
  evidence_id?: string | null;
  source: string;
  summary: string;
  key_fields: Record<string, unknown>;
  metadata: Record<string, unknown>;
  artifact_ref: string | null;
  timestamp: string;
}

export interface ChatHandoff {
  required: boolean;
  summary: string | null;
}

export interface ChatResponse {
  request_id: string;
  run_id: string;
  thread_id: string;
  status: "decision_ready" | "completed" | "waiting_user" | "transferred" | "closed";
  final_status?: string | null;
  understanding: RequestUnderstanding;
  decision: ActionDecision;
  trace: TraceEntry[];
  final_reply?: string | null;
  evidence?: ChatEvidence[];
  handoff?: ChatHandoff | null;
}

export interface ApiErrorEnvelope {
  error: {
    code: string;
    message: string;
    request_id: string;
    run_id?: string;
  };
}
