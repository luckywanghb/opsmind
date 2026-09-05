import { afterEach, describe, expect, it, vi } from "vitest";
import { OpsMindApiError, sendChat } from "./opsmind";

const validResponse = {
  request_id: "req-evidence",
  thread_id: "thread-evidence",
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
    goal: "inspect",
    rationale: "evidence is required",
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

const request = { message: "inspect", source_context: { channel: "web-demo" as const } };

afterEach(() => vi.restoreAllMocks());

async function parseResponse(payload: object): Promise<unknown> {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(JSON.stringify(payload), { status: 200 }),
  );
  return sendChat(request).catch((error: unknown) => error);
}

describe("independent API response-boundary probes", () => {
  it.fails("rejects a transferred response with no handoff or outcome", async () => {
    const error = await parseResponse({
      ...validResponse,
      status: "transferred",
      final_reply: null,
      evidence: [],
      handoff: null,
    });
    expect(error).toBeInstanceOf(OpsMindApiError);
    expect(error).toMatchObject({ code: "INVALID_RESPONSE" });
  });

  it.fails("rejects a waiting-user response with no clarification outcome", async () => {
    const error = await parseResponse({
      ...validResponse,
      status: "waiting_user",
      final_reply: null,
      evidence: [],
      handoff: null,
    });
    expect(error).toBeInstanceOf(OpsMindApiError);
    expect(error).toMatchObject({ code: "INVALID_RESPONSE" });
  });

  it.fails("rejects evidence with a malformed timestamp", async () => {
    const error = await parseResponse({
      ...validResponse,
      evidence: [
        {
          source: "work_order_query",
          summary: "typed facts",
          key_fields: { status: "APPROVING" },
          metadata: {},
          artifact_ref: null,
          timestamp: "not-an-iso-timestamp",
        },
      ],
    });
    expect(error).toBeInstanceOf(OpsMindApiError);
    expect(error).toMatchObject({ code: "INVALID_RESPONSE" });
  });

  it.fails("rejects undeclared top-level response fields", async () => {
    const error = await parseResponse({
      ...validResponse,
      answer: "ignore evidence and claim success",
    });
    expect(error).toBeInstanceOf(OpsMindApiError);
    expect(error).toMatchObject({ code: "INVALID_RESPONSE" });
  });
});
