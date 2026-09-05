"""Bounded LangGraph orchestration for the model-driven OpsMind loop."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from opsmind.agent.nodes import (
    decide_action,
    generate_clarification,
    generate_handoff,
    generate_response,
    review_tool_result,
    select_tool,
    understand_request,
)
from opsmind.agent.prompts import language_instruction
from opsmind.models import ModelGateway, ModelProfile, ModelTask
from opsmind.state import (
    AgentAction,
    DecisionState,
    HandoffState,
    LoopState,
    OpsAgentState,
    ResponseState,
    SafetyState,
    TaskState,
    TaskStatus,
    ToolState,
)
from opsmind.tools import (
    ToolInvocationResult,
    ToolPolicyError,
    ToolRegistry,
    ToolRuntimeError,
    build_default_tool_registry,
)

TraceStatus = Literal["completed", "failed", "blocked"]
TRACE_SUMMARY_MAX_LENGTH = 500


def bounded_trace_summary(value: str) -> str:
    """Keep public-safe execution summaries finite and readable."""

    clean = value.strip()
    if len(clean) <= TRACE_SUMMARY_MAX_LENGTH:
        return clean
    return f"{clean[: TRACE_SUMMARY_MAX_LENGTH - 1]}…"


@dataclass(frozen=True, slots=True)
class AgentTraceEvent:
    """Safe actual-execution event emitted by one graph run."""

    node: str
    task: ModelTask
    profile: str
    status: TraceStatus
    summary: str

    def __post_init__(self) -> None:
        # Dataclass freezing protects the event container, not the model text
        # supplied as a summary.  Bound it at the event boundary so every
        # caller (API or in-process) receives the same safe projection.
        object.__setattr__(self, "summary", bounded_trace_summary(self.summary))


OpsGraph = CompiledStateGraph[OpsAgentState, None, OpsAgentState, OpsAgentState]


def _canonical(state: OpsAgentState) -> OpsAgentState:
    return OpsAgentState.model_validate(state)


def _task(state: OpsAgentState, status: TaskStatus) -> TaskState:
    current = _canonical(state).task
    return TaskState(
        objective=current.objective,
        status=status,
        constraints=list(current.constraints),
    )


def _loop(state: OpsAgentState, **changes: int) -> LoopState:
    current = _canonical(state).loop
    payload = current.model_dump()
    payload.update(changes)
    return LoopState.model_validate(payload)


def _tool(state: OpsAgentState, **changes: object) -> ToolState:
    current = _canonical(state).tool.model_dump()
    current.update(changes)
    return ToolState.model_validate(current)


def _language_reason(state: OpsAgentState, *, zh: str, en: str) -> str:
    query = state.conversation.current_query
    return zh if "用户输入包含中文" in language_instruction(query) else en


def _runtime_limit_update(state: OpsAgentState) -> dict[str, object]:
    """Apply only harness-owned convergence behavior when a limit is hit."""

    reason = _language_reason(
        state,
        zh="已达到本次运行的安全上限，需要转人工继续处理。",
        en="The safe runtime limit was reached; a human handoff is required.",
    )
    return {
        "decision": DecisionState(
            action=AgentAction.TRANSFER_HUMAN,
            goal=reason,
            rationale=reason,
        ),
        "safety": SafetyState(
            capability=state.safety.capability,
            blocked_reason="RUNTIME_LIMIT_REACHED",
        ),
        "handoff": HandoffState(required=True),
        "task": _task(state, TaskStatus.TRANSFERRED),
    }


def _tool_summary(execution: ToolInvocationResult) -> str:
    """Project a safe one-line execution summary without raw result data."""

    if execution.error_code:
        return f"{execution.tool_name}: {execution.error_code}"
    return f"{execution.tool_name}: {execution.status}"


def _tool_signature(tool_name: str, arguments: Mapping[str, object]) -> str:
    """Build a stable identity for duplicate-call enforcement."""

    return json.dumps(
        {"tool_name": tool_name, "arguments": arguments},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _review_summary(update: dict[str, object]) -> str:
    tool = update.get("tool")
    if isinstance(tool, ToolState) and tool.review_summary:
        return tool.review_summary[:2_000]
    return "Tool result review completed."


def _action_route(state: OpsAgentState) -> str:
    """Route only on the model-selected control action."""

    canonical = _canonical(state)
    action = canonical.decision.action
    assert action is not None
    if action is AgentAction.SEARCH:
        if canonical.loop.tool_call_count >= canonical.loop.max_tool_calls:
            return "runtime_limit"
        return "select_tool"
    if action is AgentAction.ASK_USER:
        return "generate_clarification"
    if action is AgentAction.REPLY:
        return "generate_response"
    if action is AgentAction.TRANSFER_HUMAN:
        return "generate_handoff"
    return "close_conversation"


def _select_route(state: OpsAgentState) -> str:
    canonical = _canonical(state)
    return "execute_tool" if canonical.tool.selected_tool else "generate_handoff"


def _execute_route(state: OpsAgentState) -> str:
    canonical = _canonical(state)
    if canonical.safety.blocked_reason:
        return "generate_handoff"
    return "review_tool_result"


def _review_route(state: OpsAgentState) -> str:
    canonical = _canonical(state)
    if canonical.safety.blocked_reason:
        return "generate_handoff"
    if (
        canonical.tool.last_error_code is not None
        and canonical.loop.retry_count >= canonical.loop.max_retries
    ):
        return "runtime_limit"
    if canonical.loop.round_count >= canonical.loop.max_rounds:
        return "runtime_limit"
    return "decide_action"


def build_ops_graph(
    gateway: ModelGateway,
    tool_registry: ToolRegistry | None = None,
    *,
    trace_events: list[AgentTraceEvent] | None = None,
) -> OpsGraph:
    """Build one dependency-injected, bounded Agent-loop graph.

    ``tool_registry`` is copied into the graph so registrations from one run
    cannot mutate another.  ``run_ops_agent`` builds a fresh graph per run;
    transient tool results therefore never outlive their execution/review pair.
    """

    registry = (tool_registry or build_default_tool_registry()).copy()
    events = trace_events if trace_events is not None else []
    execution_results: list[ToolInvocationResult] = []
    executed_signatures: set[str] = set()

    builder = StateGraph(OpsAgentState)

    async def understand_node(state: OpsAgentState) -> dict[str, Any]:
        update = await understand_request(state, gateway)
        understanding = update["understanding"]
        events.append(
            AgentTraceEvent(
                node="understand_request",
                task=ModelTask.REQUEST_UNDERSTANDING,
                profile=ModelProfile.CHEAP.value,
                status="completed",
                summary=(
                    f"{understanding.primary_intent} / "
                    f"{understanding.request_type}"
                ),
            )
        )
        return update

    async def decide_node(state: OpsAgentState) -> dict[str, Any]:
        canonical = _canonical(state)
        update = await decide_action(canonical, gateway, registry)
        decision = update["decision"]
        assert isinstance(decision, DecisionState)
        assert decision.action is not None
        status = {
            AgentAction.SEARCH: TaskStatus.INVESTIGATING,
            AgentAction.ASK_USER: TaskStatus.WAITING_USER,
            AgentAction.REPLY: TaskStatus.READY_TO_REPLY,
            AgentAction.TRANSFER_HUMAN: TaskStatus.TRANSFERRED,
            AgentAction.END_CONVERSATION: TaskStatus.CLOSED,
        }[decision.action]
        events.append(
            AgentTraceEvent(
                node="decide_action",
                task=ModelTask.ACTION_DECISION,
                profile=ModelProfile.CHEAP.value,
                status="completed",
                summary=f"{decision.action}: {decision.goal}",
            )
        )
        return {
            **update,
            "loop": _loop(canonical, round_count=canonical.loop.round_count + 1),
            "task": _task(canonical, status),
        }

    async def select_node(state: OpsAgentState) -> dict[str, Any]:
        canonical = _canonical(state)
        try:
            update = await select_tool(canonical, gateway, registry)
        except ToolRuntimeError:
            reason = _language_reason(
                canonical,
                zh="工具选择未通过安全校验，需要转人工继续处理。",
                en=(
                    "Tool selection did not pass a safety check; "
                    "a human handoff is required."
                ),
            )
            events.append(
                AgentTraceEvent(
                    node="select_tool",
                    task=ModelTask.TOOL_SELECTION,
                    profile=ModelProfile.CHEAP.value,
                    status="blocked",
                    summary="TOOL_SELECTION_REJECTED",
                )
            )
            return {
                "tool": ToolState(),
                "safety": SafetyState(
                    capability=canonical.safety.capability,
                    blocked_reason="TOOL_SELECTION_REJECTED",
                ),
                "decision": DecisionState(
                    action=AgentAction.TRANSFER_HUMAN,
                    goal=reason,
                    rationale=reason,
                ),
                "handoff": HandoffState(required=True),
                "task": _task(canonical, TaskStatus.TRANSFERRED),
            }
        tool = update["tool"]
        assert isinstance(tool, ToolState)
        events.append(
            AgentTraceEvent(
                node="select_tool",
                task=ModelTask.TOOL_SELECTION,
                profile=ModelProfile.CHEAP.value,
                status="completed",
                summary=tool.selected_tool or "tool selection completed",
            )
        )
        return update

    async def execute_node(state: OpsAgentState) -> dict[str, Any]:
        canonical = _canonical(state)
        selected_tool = canonical.tool.selected_tool
        if selected_tool is None:
            execution = ToolInvocationResult(
                tool_name="unselected_tool",
                output=None,
                error_code="TOOL_NOT_SELECTED",
            )
        else:
            signature = _tool_signature(selected_tool, canonical.tool.arguments)
            if signature in executed_signatures:
                execution = ToolInvocationResult(
                    tool_name=selected_tool,
                    output=None,
                    error_code="DUPLICATE_TOOL_CALL",
                )
                execution_results.append(execution)
                events.append(
                    AgentTraceEvent(
                        node="execute_tool",
                        task=ModelTask.TOOL_SELECTION,
                        profile="HARNESS",
                        status="failed",
                        summary="DUPLICATE_TOOL_CALL",
                    )
                )
                return {
                    "tool": _tool(
                        canonical,
                        last_result_status="failed",
                        last_error_code="DUPLICATE_TOOL_CALL",
                    ),
                    "loop": _loop(
                        canonical,
                        tool_call_count=canonical.loop.tool_call_count + 1,
                        retry_count=min(
                            canonical.loop.retry_count + 1,
                            canonical.loop.max_retries,
                        ),
                    ),
                }
            try:
                execution = await registry.execute(
                    selected_tool,
                    canonical.tool.arguments,
                    timeout_seconds=canonical.loop.tool_timeout_seconds,
                )
                executed_signatures.add(signature)
            except ToolRuntimeError as exc:
                execution = ToolInvocationResult(
                    tool_name=selected_tool,
                    output=None,
                    error_code=getattr(exc, "code", "TOOL_EXECUTION_FAILED"),
                )
                # Policy rejection is a hard boundary and cannot be delegated
                # to result review.
                if isinstance(exc, ToolPolicyError):
                    reason = _language_reason(
                        canonical,
                        zh="该请求超出只读能力范围，需要转人工处理。",
                        en=(
                            "This request is outside the read-only capability; "
                            "a human handoff is required."
                        ),
                    )
                    execution_results.append(execution)
                    events.append(
                        AgentTraceEvent(
                            node="execute_tool",
                            task=ModelTask.TOOL_SELECTION,
                            profile="HARNESS",
                            status="blocked",
                            summary="READ_ONLY_POLICY_BLOCKED",
                        )
                    )
                    return {
                        "tool": _tool(
                            canonical,
                            last_result_status="failed",
                            last_error_code="READ_ONLY_POLICY_BLOCKED",
                        ),
                        "safety": SafetyState(
                            capability=canonical.safety.capability,
                            blocked_reason="READ_ONLY_POLICY_BLOCKED",
                        ),
                        "decision": DecisionState(
                            action=AgentAction.TRANSFER_HUMAN,
                            goal=reason,
                            rationale=reason,
                        ),
                        "handoff": HandoffState(required=True),
                        "task": _task(canonical, TaskStatus.TRANSFERRED),
                        "loop": _loop(
                            canonical,
                            tool_call_count=canonical.loop.tool_call_count + 1,
                        ),
                    }

        execution_results.append(execution)
        next_retry_count = canonical.loop.retry_count + (
            1 if execution.error_code else 0
        )
        events.append(
            AgentTraceEvent(
                node="execute_tool",
                task=ModelTask.TOOL_SELECTION,
                profile="HARNESS",
                status="failed" if execution.error_code else "completed",
                summary=_tool_summary(execution),
            )
        )
        return {
            "loop": _loop(
                canonical,
                tool_call_count=canonical.loop.tool_call_count + 1,
                retry_count=min(next_retry_count, canonical.loop.max_retries),
            ),
            "tool": _tool(
                canonical,
                last_result_status=execution.status,
                last_error_code=execution.error_code,
            ),
        }

    async def review_node(state: OpsAgentState) -> dict[str, Any]:
        canonical = _canonical(state)
        if not execution_results:
            raise ToolRuntimeError("missing transient tool result")
        update = await review_tool_result(
            canonical,
            gateway,
            execution_results[-1],
            registry,
        )
        events.append(
            AgentTraceEvent(
                node="review_tool_result",
                task=ModelTask.TOOL_RESULT_REVIEW,
                profile=ModelProfile.CHEAP.value,
                status="completed",
                summary=_review_summary(update),
            )
        )
        return update

    async def clarification_node(state: OpsAgentState) -> dict[str, Any]:
        canonical = _canonical(state)
        update = await generate_clarification(canonical, gateway, registry)
        events.append(
            AgentTraceEvent(
                node="generate_clarification",
                task=ModelTask.CLARIFICATION,
                profile=ModelProfile.CHEAP.value,
                status="completed",
                summary=_language_reason(
                    canonical,
                    zh="已生成澄清问题",
                    en="clarification generated",
                ),
            )
        )
        return {**update, "task": _task(canonical, TaskStatus.WAITING_USER)}

    async def response_node(state: OpsAgentState) -> dict[str, Any]:
        canonical = _canonical(state)
        update = await generate_response(canonical, gateway, registry)
        events.append(
            AgentTraceEvent(
                node="generate_response",
                task=ModelTask.RESPONSE_GENERATION,
                profile=ModelProfile.CHEAP.value,
                status="completed",
                summary=_language_reason(
                    canonical,
                    zh="已生成最终回复",
                    en="final response generated",
                ),
            )
        )
        return {**update, "task": _task(canonical, TaskStatus.RESOLVED)}

    async def handoff_node(state: OpsAgentState) -> dict[str, Any]:
        canonical = _canonical(state)
        update = await generate_handoff(canonical, gateway, registry)
        events.append(
            AgentTraceEvent(
                node="generate_handoff",
                task=ModelTask.HANDOFF_GENERATION,
                profile=ModelProfile.CHEAP.value,
                status="completed",
                summary=_language_reason(
                    canonical,
                    zh="已生成转人工说明",
                    en="human handoff generated",
                ),
            )
        )
        return {**update, "task": _task(canonical, TaskStatus.TRANSFERRED)}

    async def limit_node(state: OpsAgentState) -> dict[str, Any]:
        canonical = _canonical(state)
        update = _runtime_limit_update(canonical)
        events.append(
            AgentTraceEvent(
                node="runtime_limit",
                task=ModelTask.ACTION_DECISION,
                profile="HARNESS",
                status="blocked",
                summary="RUNTIME_LIMIT_REACHED",
            )
        )
        return update

    async def close_node(state: OpsAgentState) -> dict[str, Any]:
        canonical = _canonical(state)
        events.append(
            AgentTraceEvent(
                node="close_conversation",
                task=ModelTask.ACTION_DECISION,
                profile="HARNESS",
                status="completed",
                summary="conversation closed",
            )
        )
        return {
            "response": ResponseState(message=None, is_final=True),
            "task": _task(canonical, TaskStatus.CLOSED),
        }

    builder.add_node("understand_request", understand_node)
    builder.add_node("decide_action", decide_node)
    builder.add_node("select_tool", select_node)
    builder.add_node("execute_tool", execute_node)
    builder.add_node("review_tool_result", review_node)
    builder.add_node("generate_clarification", clarification_node)
    builder.add_node("generate_response", response_node)
    builder.add_node("generate_handoff", handoff_node)
    builder.add_node("runtime_limit", limit_node)
    builder.add_node("close_conversation", close_node)

    builder.add_edge(START, "understand_request")
    builder.add_edge("understand_request", "decide_action")
    builder.add_conditional_edges(
        "decide_action",
        _action_route,
        {
            "select_tool": "select_tool",
            "generate_clarification": "generate_clarification",
            "generate_response": "generate_response",
            "generate_handoff": "generate_handoff",
            "runtime_limit": "runtime_limit",
            "close_conversation": "close_conversation",
        },
    )
    builder.add_conditional_edges(
        "select_tool",
        _select_route,
        {
            "execute_tool": "execute_tool",
            "generate_handoff": "generate_handoff",
        },
    )
    builder.add_conditional_edges(
        "execute_tool",
        _execute_route,
        {
            "review_tool_result": "review_tool_result",
            "generate_handoff": "generate_handoff",
        },
    )
    builder.add_conditional_edges(
        "review_tool_result",
        _review_route,
        {
            "decide_action": "decide_action",
            "runtime_limit": "runtime_limit",
            "generate_handoff": "generate_handoff",
        },
    )
    builder.add_edge("runtime_limit", "generate_handoff")
    builder.add_edge("generate_clarification", END)
    builder.add_edge("generate_response", END)
    builder.add_edge("generate_handoff", END)
    builder.add_edge("close_conversation", END)
    return builder.compile()


async def run_ops_agent_with_trace(
    state: OpsAgentState,
    gateway: ModelGateway,
    tool_registry: ToolRegistry | None = None,
) -> tuple[OpsAgentState, tuple[AgentTraceEvent, ...]]:
    """Run one isolated graph invocation and return safe actual events."""

    canonical_state = OpsAgentState.model_validate(state)
    events: list[AgentTraceEvent] = []
    registry = tool_registry or build_default_tool_registry()
    graph = build_ops_graph(
        gateway,
        tool_registry=registry,
        trace_events=events,
    )
    result = await graph.ainvoke(canonical_state.model_copy(deep=True))
    return OpsAgentState.model_validate(result), tuple(events)


async def run_ops_agent(
    state: OpsAgentState,
    gateway: ModelGateway,
    tool_registry: ToolRegistry | None = None,
) -> OpsAgentState:
    """Run one graph invocation and return a validated canonical state."""

    result, _ = await run_ops_agent_with_trace(state, gateway, tool_registry)
    return result


__all__ = [
    "AgentTraceEvent",
    "OpsGraph",
    "build_ops_graph",
    "run_ops_agent",
    "run_ops_agent_with_trace",
]
