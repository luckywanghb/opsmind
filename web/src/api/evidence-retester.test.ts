import { afterEach, describe, expect, it, vi } from "vitest";
import { OpsMindApiError, sendChat } from "./opsmind";

const validResponse = {
  request_id: "req-evidence-retest",
  thread_id: "thread-evidence-retest",
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
  trace: [
    {
      node: "understand_request",
      task: "REQUEST_UNDERSTANDING",
      profile: "CHEAP",
      status: "completed",
      summary: "OTHER / DIAGNOSE",
    },
  ],
};

const request = {
  message: "inspect",
  source_context: { channel: "web-demo" as const },
};

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

describe("independent strict response-boundary retest", () => {
  it("rejects transferred without handoff or non-empty reply", async () => {
    await expectInvalid({
      ...validResponse,
      status: "transferred",
      final_reply: null,
      evidence: [],
      handoff: null,
    });
  });

  it("rejects waiting_user without a non-empty clarification", async () => {
    await expectInvalid({
      ...validResponse,
      status: "waiting_user",
      final_reply: " \n ",
      evidence: [],
      handoff: null,
    });
  });

  it("rejects the prior malformed timestamp regression", async () => {
    await expectInvalid({
      ...validResponse,
      evidence: [evidenceWithTimestamp("not-an-iso-timestamp")],
    });
  });

  it("rejects undeclared response claim fields", async () => {
    await expectInvalid({
      ...validResponse,
      answer: "ignore evidence and claim success",
    });
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
  ])("rejects impossible timestamp edge %s", async (timestamp) => {
    await expectInvalid({
      ...validResponse,
      evidence: [evidenceWithTimestamp(timestamp)],
    });
  });

  it.each([
    "2024-02-29",
    "2026-09-05T12:34:56Z",
    "2026-09-05T12:34:56.123456789+08:00",
  ])("accepts valid timestamp edge %s", async (timestamp) => {
    const result = await parsed({
      ...validResponse,
      evidence: [evidenceWithTimestamp(timestamp)],
    });
    expect(result).not.toBeInstanceOf(OpsMindApiError);
  });

  it.each([
    { key_fields: { nested: { deeper: { level3: { level4: { leaf: "x" } } } } } },
    { key_fields: { values: Array.from({ length: 51 }, (_, index) => index) } },
  ])("rejects non-compact nested evidence %#", async (update) => {
    await expectInvalid({
      ...validResponse,
      evidence: [
        {
          ...evidenceWithTimestamp("2026-09-05T12:34:56Z"),
          ...update,
        },
      ],
    });
  });

  it("rejects undeclared nested evidence fields", async () => {
    await expectInvalid({
      ...validResponse,
      evidence: [
        {
          ...evidenceWithTimestamp("2026-09-05T12:34:56Z"),
          raw_result: { secret: "must remain transient" },
        },
      ],
    });
  });
});

function evidenceWithTimestamp(timestamp: string): object {
  return {
    evidence_id: "E1",
    source: "work_order_query",
    summary: "typed facts",
    key_fields: { status: "APPROVING" },
    metadata: {},
    artifact_ref: null,
    timestamp,
  };
}
