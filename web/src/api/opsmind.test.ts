import { afterEach, describe, expect, it, vi } from "vitest";
import { getEval, listEvals, OpsMindApiError, runEval, sendChat } from "./opsmind";

const response = {
  request_id: "req-42",
  run_id: "run-42",
  thread_id: "thread-7",
  status: "decision_ready",
  understanding: { primary_intent: "WORKFLOW_ISSUE", request_type: "DIAGNOSE", symptom: "waiting", entities: { work_order: "WO-42" }, risk_signal: "NONE", uncertainty: null },
  decision: { action: "SEARCH", goal: "Inspect state", rationale: "Evidence is required" },
  trace: [{ node: "understand_request", task: "REQUEST_UNDERSTANDING", profile: "CHEAP", status: "completed", summary: "WORKFLOW_ISSUE / DIAGNOSE" }],
};

afterEach(() => vi.restoreAllMocks());

describe("sendChat", () => {
  it("posts and returns a typed Phase-1 response", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(response), { status: 200 }));
    await expect(sendChat({ message: "why", source_context: { channel: "web-demo" } })).resolves.toEqual(response);
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/chat", expect.objectContaining({ method: "POST", body: JSON.stringify({ message: "why", source_context: { channel: "web-demo" } }) }));
  });

  it.each([
    [422, "REQUEST_VALIDATION_FAILED", "请求格式不正确"],
    [502, "MODEL_INVOCATION_FAILED", "模型服务暂时不可用"],
    [500, "INTERNAL_SERVER_ERROR", "服务发生异常"],
  ])("maps %s errors safely and preserves request_id", async (status, code, message) => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ error: { code, message: "private detail", request_id: "req-error" } }), { status }));
    const error = await sendChat({ message: "why", source_context: { channel: "web-demo" } }).catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(OpsMindApiError);
    expect(error).toMatchObject({ code, requestId: "req-error", status });
    expect((error as Error).message).toContain(message);
    expect((error as Error).message).not.toContain("private detail");
  });

  it("preserves a post-start failure run_id for support correlation", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ error: { code: "MODEL_INVOCATION_FAILED", message: "private detail", request_id: "req-error", run_id: "run-error" } }), { status: 502 }));
    const error = await sendChat({ message: "why", source_context: { channel: "web-demo" } }).catch((caught: unknown) => caught);
    expect(error).toMatchObject({ code: "MODEL_INVOCATION_FAILED", requestId: "req-error", runId: "run-error", status: 502 });
  });

  it("rejects malformed successful trace data before it reaches the UI", async () => {
    const malformed = { ...response, trace: [{ node: "understand_request", status: "completed" }] };
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(malformed), { status: 200 }));
    const error = await sendChat({ message: "why", source_context: { channel: "web-demo" } }).catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(OpsMindApiError);
    expect(error).toMatchObject({ code: "INVALID_RESPONSE" });
  });

  it("rejects unknown backend enum values and invalid nullable fields", async () => {
    const malformed = { ...response, understanding: { ...response.understanding, primary_intent: "WORK_ORDER", symptom: 42 } };
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(malformed), { status: 200 }));
    const error = await sendChat({ message: "why", source_context: { channel: "web-demo" } }).catch((caught: unknown) => caught);
    expect(error).toMatchObject({ code: "INVALID_RESPONSE" });
  });

  it("accepts every canonical model task exposed by the backend contract", async () => {
    const futureTrace = { ...response, trace: [{ ...response.trace[0], task: "TOOL_SELECTION" }] };
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(futureTrace), { status: 200 }));
    await expect(sendChat({ message: "why", source_context: { channel: "web-demo" } })).resolves.toEqual(futureTrace);
  });

  it("rejects malformed evidence metadata before rendering", async () => {
    const malformed = {
      ...response,
      evidence: [{ source: "tool", summary: "facts", key_fields: {}, metadata: "private-detail", artifact_ref: null, timestamp: "2026-09-04T00:00:00Z" }],
    };
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(malformed), { status: 200 }));
    const error = await sendChat({ message: "why", source_context: { channel: "web-demo" } }).catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(OpsMindApiError);
    expect(error).toMatchObject({ code: "INVALID_RESPONSE" });
  });

  it("rejects a completed response that has no final reply, evidence, or handoff", async () => {
    const malformed = {
      ...response,
      status: "completed",
      final_status: "RESOLVED",
      final_reply: null,
      evidence: [],
      handoff: null,
    };
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(malformed), { status: 200 }));
    const error = await sendChat({ message: "why", source_context: { channel: "web-demo" } }).catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(OpsMindApiError);
    expect(error).toMatchObject({ code: "INVALID_RESPONSE" });
  });

  it("accepts a legitimate closed response without a reply or evidence", async () => {
    const closed = {
      ...response,
      status: "closed",
      final_status: "CLOSED",
      final_reply: null,
      evidence: [],
      handoff: null,
    };
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(closed), { status: 200 }));
    await expect(sendChat({ message: "thanks", source_context: { channel: "web-demo" } })).resolves.toEqual(closed);
  });
});

const evalAssertion = {
  assertion_id: "status",
  type: "terminal_status_is",
  blocking: true,
  status: "PASS",
  expected_safe: "COMPLETED",
  actual_safe: "COMPLETED",
  message: "Terminal status matches.",
};

const completeEvalJob = {
  eval_job_id: "eval-42",
  suite_id: "opsmind-golden",
  suite_version: "0.1",
  lifecycle_status: "COMPLETED",
  case_count: 2,
  passed_count: 1,
  failed_count: 1,
  error_count: 0,
  started_at: "2026-09-06T00:00:00Z",
  completed_at: "2026-09-06T00:00:01Z",
  duration_ms: 1_000,
  app_version: "0.1.0",
  build_sha: "build-42",
  runtime_identity: "mock",
  error_code: null,
  case_results: [
    {
      eval_job_id: "eval-42",
      case_id: "C01",
      title: "Operation guidance",
      status: "PASS",
      known_gap: null,
      run_ids: ["run-1"],
      assertions: [evalAssertion],
      started_at: "2026-09-06T00:00:00Z",
      completed_at: "2026-09-06T00:00:00Z",
      duration_ms: 250,
      error_code: null,
    },
    {
      eval_job_id: "eval-42",
      case_id: "C03",
      title: "Missing permission",
      status: "FAIL",
      known_gap: "SYNTHETIC_EXPECTATION",
      run_ids: ["run-2"],
      assertions: [{ ...evalAssertion, assertion_id: "permission", status: "FAIL", actual_safe: "missing" }],
      started_at: "2026-09-06T00:00:00Z",
      completed_at: "2026-09-06T00:00:00Z",
      duration_ms: 300,
      error_code: null,
    },
  ],
  case_runs: [
    { eval_job_id: "eval-42", case_id: "C01", turn_index: 0, run_id: "run-1" },
    { eval_job_id: "eval-42", case_id: "C03", turn_index: 0, run_id: "run-2" },
  ],
};

const evalSummary = {
  eval_job_id: "eval-42",
  suite_id: "opsmind-golden",
  suite_version: "0.1",
  lifecycle_status: "COMPLETED",
  case_count: 2,
  passed_count: 1,
  failed_count: 1,
  error_count: 0,
  started_at: "2026-09-06T00:00:00Z",
  completed_at: "2026-09-06T00:00:01Z",
  duration_ms: 1_000,
  app_version: "0.1.0",
  build_sha: "build-42",
  runtime_identity: "mock",
  error_code: null,
};

describe("Eval API client", () => {
  it("lists valid history and accepts an empty history", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(new Response(JSON.stringify([evalSummary]), { status: 200 }));
    await expect(listEvals()).resolves.toEqual([evalSummary]);
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/evals?limit=20", expect.objectContaining({ method: "GET" }));

    fetchMock.mockResolvedValueOnce(new Response("[]", { status: 200 }));
    await expect(listEvals(20)).resolves.toEqual([]);
  });

  it.each([
    ["malformed count", { ...evalSummary, case_count: 1.5 }],
    ["invalid lifecycle", { ...evalSummary, lifecycle_status: "DONE" }],
    ["unknown field", { ...evalSummary, private_detail: "secret" }],
  ])("rejects %s history data", async (_label, malformed) => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify([malformed]), { status: 200 }));
    await expect(listEvals()).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  });

  it("maps safe API and network errors for history", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(new Response(JSON.stringify({ error: { code: "EVAL_PERSISTENCE_UNAVAILABLE", message: "private SQL detail", request_id: "req-1" } }), { status: 503 }));
    const serverError = await listEvals().catch((error: unknown) => error);
    expect(serverError).toBeInstanceOf(OpsMindApiError);
    expect(serverError).toMatchObject({ code: "EVAL_PERSISTENCE_UNAVAILABLE", requestId: "req-1", status: 503 });
    expect((serverError as Error).message).not.toContain("private SQL detail");

    vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(new Error("offline"));
    await expect(listEvals()).rejects.toMatchObject({ code: "NETWORK_ERROR" });
  });

  it("gets a complete job and validates case, assertion, and run relations", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(completeEvalJob), { status: 200 }));
    await expect(getEval("eval-42")).resolves.toEqual(completeEvalJob);
  });

  it.each([
    ["malformed case", { ...completeEvalJob, case_results: [{ ...completeEvalJob.case_results[0], run_ids: [42] }] }],
    ["malformed assertion", { ...completeEvalJob, case_results: [{ ...completeEvalJob.case_results[0], assertions: [{ ...evalAssertion, status: "UNKNOWN" }] }, completeEvalJob.case_results[1]] }],
    ["malformed run relation", { ...completeEvalJob, case_runs: [{ ...completeEvalJob.case_runs[0], run_id: 42 }] }],
  ])("rejects %s detail data", async (_label, malformed) => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(malformed), { status: 200 }));
    await expect(getEval("eval-42")).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  });

  it("maps EVAL_NOT_FOUND without exposing backend details", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ error: { code: "EVAL_NOT_FOUND", message: "database path /private", request_id: "req-404" } }), { status: 404 }));
    const error = await getEval("missing").catch((caught: unknown) => caught);
    expect(error).toMatchObject({ code: "EVAL_NOT_FOUND", requestId: "req-404", status: 404 });
    expect((error as Error).message).not.toContain("/private");
  });

  it("runs the official suite with a typed complete response", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(completeEvalJob), { status: 200 }));
    await expect(runEval()).resolves.toEqual(completeEvalJob);
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/evals/run", expect.objectContaining({ method: "POST", body: JSON.stringify({ suite_id: "opsmind-golden" }) }));
  });

  it("maps run failures and malformed run responses safely", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(new Response(JSON.stringify({ error: { code: "EVAL_RUN_FAILED", message: "provider traceback", request_id: "req-run" } }), { status: 500 }));
    await expect(runEval()).rejects.toMatchObject({ code: "EVAL_RUN_FAILED" });

    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(new Response(JSON.stringify({ ...completeEvalJob, passed_count: Number.NaN }), { status: 200 }));
    await expect(runEval()).rejects.toMatchObject({ code: "INVALID_RESPONSE" });

    vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(new Error("offline"));
    await expect(runEval()).rejects.toMatchObject({ code: "NETWORK_ERROR" });
  });
});
