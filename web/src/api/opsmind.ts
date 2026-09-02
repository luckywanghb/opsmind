import type { ApiErrorEnvelope, ChatRequest, ChatResponse } from "../types/api";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "") ?? "";

export class OpsMindApiError extends Error {
  constructor(
    public readonly code: string,
    message: string,
    public readonly requestId?: string,
    public readonly status?: number,
  ) {
    super(message);
    this.name = "OpsMindApiError";
  }
}

const isObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

function isChatResponse(value: unknown): value is ChatResponse {
  if (!isObject(value) || !isObject(value.understanding) || !isObject(value.decision)) return false;
  const trace = value.trace;
  return (
    typeof value.request_id === "string" &&
    typeof value.thread_id === "string" &&
    value.status === "decision_ready" &&
    typeof value.understanding.primary_intent === "string" &&
    typeof value.understanding.request_type === "string" &&
    isObject(value.understanding.entities) &&
    typeof value.understanding.risk_signal === "string" &&
    typeof value.decision.action === "string" &&
    typeof value.decision.goal === "string" &&
    typeof value.decision.rationale === "string" &&
    Array.isArray(trace) &&
    trace.every((entry) => isObject(entry) && typeof entry.node === "string" && entry.status === "completed")
  );
}

function isErrorEnvelope(value: unknown): value is ApiErrorEnvelope {
  return (
    isObject(value) &&
    isObject(value.error) &&
    typeof value.error.code === "string" &&
    typeof value.error.message === "string" &&
    typeof value.error.request_id === "string"
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
      );
    }
    throw new OpsMindApiError("HTTP_ERROR", "服务返回了无法识别的错误。", undefined, response.status);
  }

  if (!isChatResponse(data)) {
    throw new OpsMindApiError("INVALID_RESPONSE", "服务响应格式异常，请稍后重试。");
  }
  return data;
}
