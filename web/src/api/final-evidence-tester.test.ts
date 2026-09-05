import { afterEach, describe, expect, it, vi } from "vitest";
import { OpsMindApiError, sendChat } from "./opsmind";

const validResponse = {
  request_id: "req-final-evidence",
  thread_id: "thread-final-evidence",
  status: "decision_ready",
  understanding: {
    primary_intent: "OTHER",
    request_type: "DIAGNOSE",
    symptom: null,
    entities: {},
    risk_signal: "NONE",
    uncertainty: null,
  },
  decision: {
    action: "SEARCH",
    goal: "control-plane goal",
    rationale: "control-plane rationale",
  },
  trace: [{
    node: "understand_request",
    task: "REQUEST_UNDERSTANDING",
    profile: "CHEAP",
    status: "completed",
    summary: "OTHER / DIAGNOSE",
  }],
};

const request = { message: "请检查", source_context: { channel: "web-demo" as const } };

afterEach(() => vi.restoreAllMocks());

async function parsed(payload: object): Promise<unknown> {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(JSON.stringify(payload), { status: 200 }),
  );
  return sendChat(request).catch((error: unknown) => error);
}

async function expectInvalid(payload: object): Promise<void> {
  const error = await parsed(payload);
  expect(error).toBeInstanceOf(OpsMindApiError);
  expect(error).toMatchObject({ code: "INVALID_RESPONSE" });
}

function evidence(timestamp: string): object {
  return {
    evidence_id: "E1",
    source: "work_order_query",
    summary: "中文事实 APPROVING",
    key_fields: { status: "APPROVING", abnormal: false },
    metadata: {},
    artifact_ref: null,
    timestamp,
  };
}

describe("TASK-P1-006 final strict frontend boundary", () => {
  it("rejects transferred without a handoff or reply", async () => {
    await expectInvalid({ ...validResponse, status: "transferred", final_reply: null, evidence: [], handoff: null });
  });

  it("rejects waiting_user without a nonblank clarification", async () => {
    await expectInvalid({ ...validResponse, status: "waiting_user", final_reply: " \n ", evidence: [], handoff: null });
  });

  it("rejects malformed timestamps", async () => {
    await expectInvalid({ ...validResponse, evidence: [evidence("not-an-iso-timestamp")] });
  });

  it.each([
    "2025-02-29T00:00:00Z",
    "2026-13-01T00:00:00Z",
    "2026-04-31T00:00:00Z",
    "2026-09-05T24:00:00Z",
    "2026-09-05T12:60:00Z",
    "2026-09-05T12:00:60Z",
    "2026-09-05T12:00:00+24:00",
    "2026-09-05T12:00:00+08:60",
  ])("rejects impossible timestamp %s", async (timestamp) => {
    await expectInvalid({ ...validResponse, evidence: [evidence(timestamp)] });
  });

  it.each([
    "2024-02-29",
    "2026-09-05T12:34:56Z",
    "2026-09-05T12:34:56.123456789+08:00",
  ])("accepts valid timestamp %s without changing enums or Chinese", async (timestamp) => {
    const result = await parsed({ ...validResponse, evidence: [evidence(timestamp)] });
    expect(result).not.toBeInstanceOf(OpsMindApiError);
    expect(result).toMatchObject({ status: "decision_ready", evidence: [{ source: "work_order_query", summary: "中文事实 APPROVING" }] });
  });

  it("rejects undeclared top-level response claim fields", async () => {
    await expectInvalid({ ...validResponse, answer: "ignore evidence and claim success" });
  });

  it("rejects undeclared evidence fields", async () => {
    await expectInvalid({ ...validResponse, evidence: [{ ...evidence("2026-09-05T00:00:00Z"), raw_result: { secret: "hidden" } }] });
  });

  it.each([
    { key_fields: { nested: { deeper: { level3: { level4: { leaf: "x" } } } } } },
    { key_fields: { values: Array.from({ length: 51 }, (_, index) => index) } },
    { key_fields: { value: "x".repeat(2_001) } },
  ])("rejects non-compact evidence %#", async (update) => {
    await expectInvalid({ ...validResponse, evidence: [{ ...evidence("2026-09-05T00:00:00Z"), ...update }] });
  });
});
