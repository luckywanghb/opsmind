import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { ChatErrorState, ChatPage } from "./ChatPage";
import { sendChat } from "../api/opsmind";

vi.mock("../api/opsmind", async () => {
  const actual = await vi.importActual<typeof import("../api/opsmind")>("../api/opsmind");
  return { ...actual, sendChat: vi.fn() };
});

const mockedSendChat = vi.mocked(sendChat);
const successfulResponse = {
  request_id: "req-42", thread_id: "thread-7", status: "completed" as const, final_status: "RESOLVED", final_reply: "工单正在审批，当前处理人是 U10108。",
  understanding: { primary_intent: "WORKFLOW_ISSUE" as const, request_type: "DIAGNOSE" as const, symptom: "Work order is waiting", entities: { work_order: "WO-42" }, risk_signal: "NONE" as const, uncertainty: null },
  decision: { action: "SEARCH" as const, goal: "Inspect current approval state", rationale: "Current node is required" },
  trace: [
    { node: "understand_request", task: "REQUEST_UNDERSTANDING" as const, profile: "CHEAP" as const, status: "completed" as const, summary: "WORKFLOW_ISSUE / DIAGNOSE" },
    { node: "decide_action", task: "ACTION_DECISION" as const, profile: "CHEAP" as const, status: "completed" as const, summary: "SEARCH: Inspect current approval state" },
    { node: "select_tool", task: "TOOL_SELECTION" as const, profile: "CHEAP" as const, status: "completed" as const, summary: "work_order_query" },
    { node: "execute_tool", task: "TOOL_SELECTION" as const, profile: "HARNESS" as const, status: "completed" as const, summary: "work_order_query: found" },
    { node: "review_tool_result", task: "TOOL_RESULT_REVIEW" as const, profile: "CHEAP" as const, status: "completed" as const, summary: "已确认工单事实" },
    { node: "decide_action", task: "ACTION_DECISION" as const, profile: "CHEAP" as const, status: "completed" as const, summary: "REPLY: 基于证据回复" },
    { node: "generate_response", task: "RESPONSE_GENERATION" as const, profile: "CHEAP" as const, status: "completed" as const, summary: "final response generated" },
  ],
  evidence: [{ source: "work_order_query", summary: "已确认工单事实", key_fields: { status: "APPROVING" }, metadata: {}, artifact_ref: null, timestamp: "2026-09-04T00:00:00Z" }],
};

beforeEach(() => mockedSendChat.mockReset());

it("shows welcome prompts before the first message", () => {
  render(<ChatPage />);
  expect(screen.getByText("你好，我是 OpsMind")).toBeInTheDocument();
  expect(screen.getByText("为什么我的工单一直停在审批中？")).toBeInTheDocument();
});

it("hides welcome, shows loading, and renders actual understanding, decision and trace", async () => {
  let resolve!: (value: typeof successfulResponse) => void;
  mockedSendChat.mockReturnValue(new Promise((done) => { resolve = done; }));
  render(<ChatPage />);
  fireEvent.change(screen.getByLabelText("输入运维问题"), { target: { value: "Why is WO-42 waiting?" } });
  fireEvent.click(screen.getByLabelText("发送消息"));
  expect(screen.queryByText("你好，我是 OpsMind")).not.toBeInTheDocument();
  expect(screen.getByText("正在理解请求并生成动作决策…")).toBeInTheDocument();
  resolve(successfulResponse);
  expect(await screen.findByText("WORKFLOW_ISSUE")).toBeInTheDocument();
  expect(screen.getByText("Inspect current approval state")).toBeInTheDocument();
  expect(screen.getByText("SEARCH: Inspect current approval state")).toBeInTheDocument();
  expect(screen.getAllByText("已完成")).toHaveLength(7);
  expect(screen.queryByText("规划中")).not.toBeInTheDocument();
  expect(screen.getByText("工单正在审批，当前处理人是 U10108。")).toBeInTheDocument();
});

it("reuses the returned thread id for another message in the same page session", async () => {
  mockedSendChat.mockResolvedValue(successfulResponse);
  render(<ChatPage />);
  const input = screen.getByLabelText("输入运维问题");
  fireEvent.change(input, { target: { value: "first" } });
  fireEvent.click(screen.getByLabelText("发送消息"));
  await screen.findByText("WORKFLOW_ISSUE");
  fireEvent.change(input, { target: { value: "second" } });
  fireEvent.click(screen.getByLabelText("发送消息"));
  await waitFor(() => expect(mockedSendChat).toHaveBeenCalledTimes(2));
  expect(mockedSendChat.mock.calls[1][0]).toMatchObject({ message: "second", thread_id: "thread-7" });
});

it("renders a safe error state with its troubleshooting id", () => {
  const onRetry = vi.fn();
  render(<ChatErrorState message="模型服务暂时不可用，请稍后重试。" requestId="req-failed" onRetry={onRetry} />);
  expect(screen.getByRole("alert")).toHaveTextContent("模型服务暂时不可用");
  expect(screen.getByRole("alert")).toHaveTextContent("req-failed");
  fireEvent.click(screen.getByRole("button", { name: "重试本次请求" }));
  expect(onRetry).toHaveBeenCalledOnce();
});

it("does not label a completed response as done when no final response exists", async () => {
  const falseCompleted = {
    ...successfulResponse,
    final_reply: null,
    evidence: [],
    handoff: null,
  };
  mockedSendChat.mockResolvedValue(falseCompleted);
  render(<ChatPage />);
  fireEvent.change(screen.getByLabelText("输入运维问题"), { target: { value: "incomplete" } });
  fireEvent.click(screen.getByLabelText("发送消息"));

  await screen.findByText("以下内容来自本次真实 Agent 运行。");
  expect(screen.queryByText("已完成请求")).not.toBeInTheDocument();
});
