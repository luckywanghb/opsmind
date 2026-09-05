import type { ApiErrorEnvelope, ChatRequest, ChatResponse } from "../types/api";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "") ?? "";

export class OpsMindApiError extends Error {
  constructor(
    public readonly code: string,
    message: string,
    public readonly requestId?: string,
    public readonly status?: number,
    public readonly runId?: string,
  ) {
    super(message);
    this.name = "OpsMindApiError";
  }
}

const isObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const primaryIntents = new Set(["SYSTEM_OPERATION", "BUSINESS_RULE", "ACCESS_ISSUE", "WORKFLOW_ISSUE", "DATA_ISSUE", "OTHER"]);
const requestTypes = new Set(["HOW_TO", "EXPLAIN", "DIAGNOSE", "CHECK_STATUS", "EXECUTE_CHANGE", "CONTINUE_CASE", "CONFIRM_RESOLVED", "OTHER"]);
const riskSignals = new Set(["NONE", "PRIVILEGED_CHANGE", "BROAD_OUTAGE", "SECURITY_SUSPECTED", "DESTRUCTIVE_OPERATION"]);
const agentActions = new Set(["ASK_USER", "SEARCH", "REPLY", "TRANSFER_HUMAN", "END_CONVERSATION"]);
const modelTasks = new Set(["REQUEST_UNDERSTANDING", "ACTION_DECISION", "TOOL_SELECTION", "TOOL_RESULT_REVIEW", "CLARIFICATION", "RESPONSE_GENERATION", "HANDOFF_GENERATION"]);
const modelProfiles = new Set(["CHEAP", "STRONG", "FALLBACK", "HARNESS"]);
const responseStatuses = new Set(["decision_ready", "completed", "waiting_user", "transferred", "closed"]);
const traceStatuses = new Set(["completed", "failed", "blocked"]);
const isNullableString = (value: unknown): value is string | null => value === null || typeof value === "string";
const isOptionalNullableString = (value: unknown): boolean => value === undefined || isNullableString(value);

const MAX_EVIDENCE_ITEMS = 50;
const MAX_EVIDENCE_COLLECTION_ITEMS = 50;
const MAX_EVIDENCE_NESTING_DEPTH = 4;
const MAX_EVIDENCE_STRING_LENGTH = 2_000;
const MAX_EVIDENCE_SERIALIZED_BYTES = 16 * 1_024;
const MAX_TRACE_SUMMARY_LENGTH = 500;

function hasOnlyKeys(value: Record<string, unknown>, allowed: ReadonlySet<string>): boolean {
  return Object.keys(value).every((key) => allowed.has(key));
}

function isFiniteJson(value: unknown): boolean {
  if (value === null || typeof value === "string" || typeof value === "boolean") return true;
  if (typeof value === "number") return Number.isFinite(value);
  if (Array.isArray(value)) return value.every(isFiniteJson);
  if (!isObject(value)) return false;
  return Object.values(value).every(isFiniteJson);
}

function isCompactJson(value: unknown, parentDepth = 0): boolean {
  if (typeof value === "string") return value.length <= MAX_EVIDENCE_STRING_LENGTH;
  if (value === null || typeof value === "boolean") return true;
  if (typeof value === "number") return Number.isFinite(value);
  if (Array.isArray(value)) {
    if (parentDepth + 1 > MAX_EVIDENCE_NESTING_DEPTH || value.length > MAX_EVIDENCE_COLLECTION_ITEMS) return false;
    return value.every((item) => isCompactJson(item, parentDepth + 1));
  }
  if (!isObject(value)) return false;
  if (parentDepth + 1 > MAX_EVIDENCE_NESTING_DEPTH || Object.keys(value).length > MAX_EVIDENCE_COLLECTION_ITEMS) return false;
  return Object.entries(value).every(([key, item]) => key.length <= MAX_EVIDENCE_STRING_LENGTH && isCompactJson(item, parentDepth + 1));
}

function utf8Length(value: unknown): number {
  try {
    const encoded = JSON.stringify(value);
    return encoded === undefined ? Number.POSITIVE_INFINITY : new TextEncoder().encode(encoded).length;
  } catch {
    return Number.POSITIVE_INFINITY;
  }
}

function isValidTimestamp(value: unknown): value is string {
  if (typeof value !== "string") return false;
  const match = /^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?(Z|[+-]\d{2}:?\d{2})?)?$/.exec(value);
  if (!match) return false;
  const [, yearText, monthText, dayText, hourText, minuteText, secondText, , zone] = match;
  const year = Number(yearText);
  const month = Number(monthText);
  const day = Number(dayText);
  if (year < 1 || year > 9_999 || month < 1 || month > 12) return false;
  const daysInMonth = new Date(Date.UTC(year, month, 0)).getUTCDate();
  if (day < 1 || day > daysInMonth) return false;
  if (hourText === undefined) return true;
  const hour = Number(hourText);
  const minute = Number(minuteText);
  const second = Number(secondText);
  if (hour > 23 || minute > 59 || second > 59) return false;
  if (zone && zone !== "Z") {
    const offset = zone.slice(1).replace(":", "");
    if (Number(offset.slice(0, 2)) > 23 || Number(offset.slice(2)) > 59) return false;
  }
  return Number.isFinite(Date.parse(value));
}

const responseKeys = new Set(["request_id", "run_id", "thread_id", "status", "final_status", "understanding", "decision", "trace", "final_reply", "evidence", "handoff"]);
const understandingKeys = new Set(["primary_intent", "request_type", "symptom", "entities", "risk_signal", "uncertainty"]);
const decisionKeys = new Set(["action", "goal", "rationale"]);
const traceKeys = new Set(["node", "task", "profile", "status", "summary"]);
const evidenceKeys = new Set(["evidence_id", "source", "summary", "key_fields", "metadata", "artifact_ref", "timestamp"]);
const handoffKeys = new Set(["required", "summary"]);

function isEvidence(value: unknown): boolean {
  if (!isObject(value) || !hasOnlyKeys(value, evidenceKeys)) return false;
  const evidenceId = value.evidence_id;
  if (!(evidenceId === undefined || evidenceId === null || (typeof evidenceId === "string" && /^E[1-9][0-9]{0,5}$/.test(evidenceId)))) return false;
  if (typeof value.source !== "string" || value.source.length > MAX_EVIDENCE_STRING_LENGTH) return false;
  if (typeof value.summary !== "string" || value.summary.length > MAX_EVIDENCE_STRING_LENGTH) return false;
  if (!isObject(value.key_fields) || !isObject(value.metadata)) return false;
  if (!isCompactJson(value.key_fields) || !isCompactJson(value.metadata)) return false;
  if (!isNullableString(value.artifact_ref) || (typeof value.artifact_ref === "string" && value.artifact_ref.length > MAX_EVIDENCE_STRING_LENGTH)) return false;
  if (!isValidTimestamp(value.timestamp)) return false;
  return utf8Length(value) <= MAX_EVIDENCE_SERIALIZED_BYTES;
}

function hasFinalReply(value: Record<string, unknown>): boolean {
  const finalReply = value.final_reply;
  return typeof finalReply === "string" && finalReply.trim().length > 0;
}

function hasRequiredHandoff(value: Record<string, unknown>): boolean {
  const handoff = value.handoff;
  return isObject(handoff) && handoff.required === true;
}

function hasResponseOutcome(value: Record<string, unknown>): boolean {
  const hasEvidence = Array.isArray(value.evidence) && value.evidence.length > 0;
  return hasFinalReply(value) || hasEvidence || hasRequiredHandoff(value);
}

function hasStatusOutcome(value: Record<string, unknown>): boolean {
  switch (value.status) {
    case "completed":
      return hasResponseOutcome(value);
    case "waiting_user":
      return hasFinalReply(value);
    case "transferred":
      return hasFinalReply(value) || hasRequiredHandoff(value);
    default:
      return true;
  }
}

function isChatResponse(value: unknown): value is ChatResponse {
  if (!isObject(value) || !isObject(value.understanding) || !isObject(value.decision)) return false;
  if (!hasOnlyKeys(value, responseKeys) || !hasOnlyKeys(value.understanding, understandingKeys) || !hasOnlyKeys(value.decision, decisionKeys)) return false;
  const trace = value.trace;
  const understanding = value.understanding;
  const decision = value.decision;
  const handoff = value.handoff;
  const evidence = value.evidence;
  if (isObject(handoff) && !hasOnlyKeys(handoff, handoffKeys)) return false;
  if (Array.isArray(trace) && !trace.every((entry) => isObject(entry) && hasOnlyKeys(entry, traceKeys))) return false;
  return (
    typeof value.request_id === "string" &&
    typeof value.run_id === "string" &&
    typeof value.thread_id === "string" &&
    responseStatuses.has(String(value.status)) &&
    primaryIntents.has(String(understanding.primary_intent)) &&
    requestTypes.has(String(understanding.request_type)) &&
    isNullableString(understanding.symptom) &&
    isObject(understanding.entities) &&
    isFiniteJson(understanding.entities) &&
    riskSignals.has(String(understanding.risk_signal)) &&
    isNullableString(understanding.uncertainty) &&
    agentActions.has(String(decision.action)) &&
    typeof decision.goal === "string" &&
    typeof decision.rationale === "string" &&
    isOptionalNullableString(value.final_status) &&
    isOptionalNullableString(value.final_reply) &&
    (evidence === undefined || (Array.isArray(evidence) && evidence.length <= MAX_EVIDENCE_ITEMS && evidence.every(isEvidence))) &&
    (handoff === undefined || handoff === null || (isObject(handoff) && typeof handoff.required === "boolean" && isNullableString(handoff.summary))) &&
    hasStatusOutcome(value) &&
    Array.isArray(trace) &&
    trace.every((entry) =>
      isObject(entry) &&
      typeof entry.node === "string" &&
      entry.node.length <= MAX_TRACE_SUMMARY_LENGTH &&
      modelTasks.has(String(entry.task)) &&
      modelProfiles.has(String(entry.profile)) &&
      traceStatuses.has(String(entry.status)) &&
      typeof entry.summary === "string" &&
      entry.summary.length <= MAX_TRACE_SUMMARY_LENGTH
    )
  );
}

function isErrorEnvelope(value: unknown): value is ApiErrorEnvelope {
  return (
    isObject(value) &&
    isObject(value.error) &&
    typeof value.error.code === "string" &&
    typeof value.error.message === "string" &&
    typeof value.error.request_id === "string" &&
    (value.error.run_id === undefined || typeof value.error.run_id === "string")
  );
}

const safeMessages: Record<string, string> = {
  REQUEST_VALIDATION_FAILED: "请求格式不正确，请检查输入后重试。",
  INVALID_AGENT_INPUT: "请求内容无法处理，请调整后重试。",
  MODEL_INVOCATION_FAILED: "模型服务暂时不可用，请稍后重试。",
  MODEL_STRUCTURED_OUTPUT_INVALID: "模型返回格式异常，请稍后重试。",
  INTERNAL_SERVER_ERROR: "服务发生异常，请稍后重试。",
};

export async function sendChat(payload: ChatRequest, signal?: AbortSignal): Promise<ChatResponse> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/api/v1/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal,
    });
  } catch {
    throw new OpsMindApiError("NETWORK_ERROR", "无法连接 OpsMind 服务，请确认后端已启动。");
  }

  const data: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    if (isErrorEnvelope(data)) {
      throw new OpsMindApiError(
        data.error.code,
        safeMessages[data.error.code] ?? "请求未能完成，请稍后重试。",
        data.error.request_id,
        response.status,
        data.error.run_id,
      );
    }
    throw new OpsMindApiError("HTTP_ERROR", "服务返回了无法识别的错误。", undefined, response.status);
  }

  if (!isChatResponse(data)) {
    throw new OpsMindApiError("INVALID_RESPONSE", "服务响应格式异常，请稍后重试。");
  }
  return data;
}
