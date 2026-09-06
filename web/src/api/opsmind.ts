import type {
  ApiErrorEnvelope,
  ChatRequest,
  ChatResponse,
  EvalAssertionResult,
  EvalCaseResult,
  EvalCaseRun,
  EvalJob,
  EvalJobSummary,
  EvalSafeValue,
  EvalRunRequest,
} from "../types/api";

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
const evalJobLifecycleStatuses = new Set(["STARTED", "COMPLETED", "FAILED"]);
const evalCaseStatuses = new Set(["PASS", "FAIL", "ERROR"]);
const evalAssertionStatuses = new Set(["PASS", "FAIL", "ERROR"]);
const isNullableString = (value: unknown): value is string | null => value === null || typeof value === "string";
const isOptionalNullableString = (value: unknown): boolean => value === undefined || isNullableString(value);

const MAX_EVIDENCE_ITEMS = 50;
const MAX_EVIDENCE_COLLECTION_ITEMS = 50;
const MAX_EVIDENCE_NESTING_DEPTH = 4;
const MAX_EVIDENCE_STRING_LENGTH = 2_000;
const MAX_EVIDENCE_SERIALIZED_BYTES = 16 * 1_024;
const MAX_TRACE_SUMMARY_LENGTH = 500;
const MAX_EVAL_STRING_LENGTH = 512;
const MAX_EVAL_SAFE_VALUE_ITEMS = 32;
const MAX_EVAL_SAFE_VALUE_DEPTH = 8;
const MAX_EVAL_CASES = 256;
const MAX_EVAL_CASE_RUNS = 512;

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

function isEvalSafeValue(value: unknown): value is EvalSafeValue {
  const pending: Array<{ value: unknown; depth: number }> = [{ value, depth: 0 }];
  while (pending.length > 0) {
    const current = pending.pop();
    if (!current) return false;
    const currentValue = current.value;
    if (currentValue === null || typeof currentValue === "boolean") continue;
    if (typeof currentValue === "string") {
      if (currentValue.length > MAX_EVAL_STRING_LENGTH) return false;
      continue;
    }
    if (typeof currentValue === "number") {
      if (!Number.isFinite(currentValue)) return false;
      continue;
    }
    if (current.depth >= MAX_EVAL_SAFE_VALUE_DEPTH) return false;
    if (Array.isArray(currentValue)) {
      if (currentValue.length > MAX_EVAL_SAFE_VALUE_ITEMS) return false;
      for (const item of currentValue) pending.push({ value: item, depth: current.depth + 1 });
      continue;
    }
    if (!isObject(currentValue) || Object.keys(currentValue).length > MAX_EVAL_SAFE_VALUE_ITEMS) return false;
    for (const [key, item] of Object.entries(currentValue)) {
      if (key.length > MAX_EVAL_STRING_LENGTH) return false;
      pending.push({ value: item, depth: current.depth + 1 });
    }
  }
  return true;
}

function isFiniteNonNegativeInteger(value: unknown, maximum?: number): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0 && (maximum === undefined || value <= maximum);
}

function isNullableFiniteNonNegativeNumber(value: unknown): value is number | null {
  return value === null || (typeof value === "number" && Number.isFinite(value) && value >= 0);
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

const evalJobSummaryKeys = new Set([
  "eval_job_id",
  "suite_id",
  "suite_version",
  "lifecycle_status",
  "case_count",
  "passed_count",
  "failed_count",
  "error_count",
  "started_at",
  "completed_at",
  "duration_ms",
  "app_version",
  "build_sha",
  "runtime_identity",
  "error_code",
]);
const evalAssertionKeys = new Set(["assertion_id", "type", "blocking", "status", "expected_safe", "actual_safe", "message"]);
const evalCaseKeys = new Set([
  "eval_job_id",
  "case_id",
  "title",
  "status",
  "known_gap",
  "run_ids",
  "assertions",
  "started_at",
  "completed_at",
  "duration_ms",
  "error_code",
]);
const evalCaseRunKeys = new Set(["eval_job_id", "case_id", "turn_index", "run_id"]);
const evalJobKeys = new Set([...evalJobSummaryKeys, "case_results", "case_runs"]);

function isBoundedText(value: unknown, maximum = MAX_EVAL_STRING_LENGTH): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= maximum;
}

function isEvalAssertionResult(value: unknown): value is EvalAssertionResult {
  if (!isObject(value) || !hasOnlyKeys(value, evalAssertionKeys)) return false;
  return (
    isBoundedText(value.assertion_id) &&
    isBoundedText(value.type) &&
    typeof value.blocking === "boolean" &&
    evalAssertionStatuses.has(String(value.status)) &&
    isEvalSafeValue(value.expected_safe) &&
    isEvalSafeValue(value.actual_safe) &&
    isBoundedText(value.message)
  );
}

function isEvalCaseResult(value: unknown): value is EvalCaseResult {
  if (!isObject(value) || !hasOnlyKeys(value, evalCaseKeys)) return false;
  if (!isBoundedText(value.eval_job_id) || !isBoundedText(value.case_id) || !isBoundedText(value.title)) return false;
  if (!evalCaseStatuses.has(String(value.status))) return false;
  if (!isNullableString(value.known_gap) || (typeof value.known_gap === "string" && value.known_gap.length > MAX_EVAL_STRING_LENGTH)) return false;
  if (!Array.isArray(value.run_ids) || value.run_ids.length > 32 || !value.run_ids.every((runId) => isBoundedText(runId, 128))) return false;
  if (!Array.isArray(value.assertions) || value.assertions.length > 128 || !value.assertions.every(isEvalAssertionResult)) return false;
  if (!isValidTimestamp(value.started_at) || !isNullableString(value.completed_at) || (typeof value.completed_at === "string" && !isValidTimestamp(value.completed_at))) return false;
  if (!isNullableFiniteNonNegativeNumber(value.duration_ms)) return false;
  if (!isNullableString(value.error_code) || (typeof value.error_code === "string" && value.error_code.length > 128)) return false;
  if (value.status === "ERROR" && !isBoundedText(value.error_code, 128)) return false;
  if (value.status !== "ERROR" && value.error_code !== null) return false;
  return true;
}

function isEvalCaseRun(value: unknown): value is EvalCaseRun {
  return (
    isObject(value) &&
    hasOnlyKeys(value, evalCaseRunKeys) &&
    isBoundedText(value.eval_job_id) &&
    isBoundedText(value.case_id) &&
    isFiniteNonNegativeInteger(value.turn_index, 31) &&
    isBoundedText(value.run_id, 128)
  );
}

function isEvalJobSummary(value: unknown, allowDetailFields = false): value is EvalJobSummary {
  if (!isObject(value) || (!allowDetailFields && !hasOnlyKeys(value, evalJobSummaryKeys))) return false;
  if (!isBoundedText(value.eval_job_id, 128) || !isBoundedText(value.suite_id, 128) || !isBoundedText(value.suite_version, 64)) return false;
  if (!evalJobLifecycleStatuses.has(String(value.lifecycle_status))) return false;
  if (!isFiniteNonNegativeInteger(value.case_count, MAX_EVAL_CASES) || !isFiniteNonNegativeInteger(value.passed_count, MAX_EVAL_CASES) || !isFiniteNonNegativeInteger(value.failed_count, MAX_EVAL_CASES) || !isFiniteNonNegativeInteger(value.error_count, MAX_EVAL_CASES)) return false;
  if (!isValidTimestamp(value.started_at) || !isNullableString(value.completed_at) || (typeof value.completed_at === "string" && !isValidTimestamp(value.completed_at))) return false;
  if (!isNullableFiniteNonNegativeNumber(value.duration_ms)) return false;
  if (!isBoundedText(value.app_version, 256) || !isNullableString(value.build_sha) || (typeof value.build_sha === "string" && value.build_sha.length > 256)) return false;
  if (!isBoundedText(value.runtime_identity, 256) || !isNullableString(value.error_code) || (typeof value.error_code === "string" && value.error_code.length > 128)) return false;
  if (value.lifecycle_status === "STARTED") {
    return value.completed_at === null && value.duration_ms === null && value.error_code === null && value.passed_count === 0 && value.failed_count === 0 && value.error_count === 0;
  }
  if (value.completed_at === null || value.duration_ms === null) return false;
  if (value.lifecycle_status === "FAILED") return value.error_code !== null && value.passed_count === 0 && value.failed_count === 0 && value.error_count === 0;
  return value.error_code === null && value.passed_count + value.failed_count + value.error_count === value.case_count;
}

function isEvalJob(value: unknown): value is EvalJob {
  if (!isEvalJobSummary(value, true) || !isObject(value) || !hasOnlyKeys(value, evalJobKeys)) return false;
  if (!Array.isArray(value.case_results) || value.case_results.length > MAX_EVAL_CASES || !value.case_results.every(isEvalCaseResult)) return false;
  if (!Array.isArray(value.case_runs) || value.case_runs.length > MAX_EVAL_CASE_RUNS || !value.case_runs.every(isEvalCaseRun)) return false;
  if (value.lifecycle_status !== "COMPLETED") return value.case_results.length === 0 && value.case_runs.length === 0;
  if (value.case_results.length !== value.case_count || value.case_results.some((result) => result.eval_job_id !== value.eval_job_id)) return false;
  const caseIds = new Set<string>();
  const expectedRelations = new Set<string>();
  for (const result of value.case_results) {
    if (caseIds.has(result.case_id)) return false;
    caseIds.add(result.case_id);
    result.run_ids.forEach((runId, turnIndex) => expectedRelations.add(`${result.case_id}:${turnIndex}:${runId}`));
  }
  for (const relation of value.case_runs) {
    if (relation.eval_job_id !== value.eval_job_id || !expectedRelations.delete(`${relation.case_id}:${relation.turn_index}:${relation.run_id}`)) return false;
  }
  return expectedRelations.size === 0;
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
  EVAL_SUITE_INVALID: "评测套件不可用，请稍后重试。",
  EVAL_NOT_FOUND: "找不到这条评测记录，请刷新后重试。",
  EVAL_PERSISTENCE_UNAVAILABLE: "评测记录暂时无法保存，请稍后重试。",
  EVAL_RUN_FAILED: "本次评测运行失败，请稍后重试。",
  RUN_PERSISTENCE_UNAVAILABLE: "运行记录暂时无法保存，请稍后重试。",
  NETWORK_ERROR: "无法连接 OpsMind 服务，请确认后端已启动。",
  INVALID_RESPONSE: "服务响应格式异常，请稍后重试。",
};

function safeApiError(data: unknown, response: Response): OpsMindApiError {
  if (isErrorEnvelope(data)) {
    return new OpsMindApiError(
      data.error.code,
      safeMessages[data.error.code] ?? "请求未能完成，请稍后重试。",
      data.error.request_id,
      response.status,
      data.error.run_id,
    );
  }
  return new OpsMindApiError("HTTP_ERROR", "服务返回了无法识别的错误。", undefined, response.status);
}

async function requestJson<T>(url: string, init: RequestInit, decoder: (value: unknown) => value is T, signal?: AbortSignal): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, { ...init, signal });
  } catch {
    throw new OpsMindApiError("NETWORK_ERROR", safeMessages.NETWORK_ERROR);
  }
  const data: unknown = await response.json().catch(() => null);
  if (!response.ok) throw safeApiError(data, response);
  if (!decoder(data)) throw new OpsMindApiError("INVALID_RESPONSE", safeMessages.INVALID_RESPONSE);
  return data;
}

export const OFFICIAL_EVAL_SUITE_ID = "opsmind-golden";

export async function listEvals(limit = 20, signal?: AbortSignal): Promise<EvalJobSummary[]> {
  const data = await requestJson<EvalJobSummary[]>(`${API_BASE_URL}/api/v1/evals?limit=${limit}`, { method: "GET" }, (value): value is EvalJobSummary[] => Array.isArray(value) && value.length <= 100 && value.every((item) => isEvalJobSummary(item)), signal);
  return data;
}

export async function getEval(evalJobId: string, signal?: AbortSignal): Promise<EvalJob> {
  return requestJson<EvalJob>(`${API_BASE_URL}/api/v1/evals/${encodeURIComponent(evalJobId)}`, { method: "GET" }, isEvalJob, signal);
}

export async function runEval(payload: EvalRunRequest = { suite_id: OFFICIAL_EVAL_SUITE_ID }, signal?: AbortSignal): Promise<EvalJob> {
  return requestJson<EvalJob>(`${API_BASE_URL}/api/v1/evals/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  }, isEvalJob, signal);
}

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
