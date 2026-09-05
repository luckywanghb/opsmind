import { afterEach, describe, expect, it, vi } from "vitest";
import { OpsMindApiError, sendChat } from "./opsmind";

const response = {
  request_id: "req-42",
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
