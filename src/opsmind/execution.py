"""Shared Agent execution boundary used by Chat and Eval runtimes."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from pydantic import JsonValue

from opsmind.agent.graph import bounded_trace_summary
from opsmind.agent.grounding import stable_evidence_items
from opsmind.api.run_observability import (
    normalized_error_code,
    persist_chat_success,
    safe_failure_steps,
)
from opsmind.api.runtime import AgentRunResult, OpsAgentRuntime
from opsmind.api.schemas import (
    AgentTraceStep,
    ChatDecision,
    ChatEvidence,
    ChatHandoff,
    ChatResponse,
    ChatUnderstanding,
)
from opsmind.evals.models import EvaluationObservation, ToolCallObservation
from opsmind.runs import RunPersistenceError, RunPersistenceService
from opsmind.state import (
    AgentAction,
    IdentityState,
    OpsAgentState,
    TaskStatus,
)


class AgentExecutionError(RuntimeError):
    """Safe wrapper retaining the real run identity for an eval error."""

    def __init__(
        self,
        *,
        run_id: str,
        request_id: str,
        thread_id: str,
        cause: Exception,
    ) -> None:
        super().__init__("Agent execution failed")
        self.run_id = run_id
        self.request_id = request_id
        self.thread_id = thread_id
        self.cause = cause
        self.error_code = normalized_error_code(cause)


@dataclass(frozen=True, slots=True)
class AgentExecutionResult:
    """Public response plus a transient safe eval observation."""

    response: ChatResponse
    evaluation_observation: EvaluationObservation

    @property
    def run_id(self) -> str:
        return self.response.run_id

    @property
    def request_id(self) -> str:
        return self.response.request_id

    @property
    def thread_id(self) -> str:
        return self.response.thread_id


def _trace_summary(result: AgentRunResult, node: str) -> str:
    if node == "understand_request":
        understanding = result.state.understanding
        return bounded_trace_summary(
            f"{understanding.primary_intent} / {understanding.request_type}"
        )
    decision = result.state.decision
    return bounded_trace_summary(
        decision.action.value if decision.action is not None else "ACTION_UNKNOWN"
    )


def _trace(result: AgentRunResult) -> list[AgentTraceStep]:
    if result.events:
        return [
            AgentTraceStep(
                node=event.node,
                task=event.task,
                profile=event.profile,
                status=event.status,
                summary=event.summary,
            )
            for event in result.events
        ]
    steps: list[AgentTraceStep] = []
    for invocation in result.invocations:
        node = invocation.request.metadata.get("node")
        if not isinstance(node, str) or not node:
            continue
        steps.append(
            AgentTraceStep(
                node=node,
                task=invocation.request.task,
                profile=invocation.request.profile,
                summary=_trace_summary(result, node),
            )
        )
    return steps


def chat_response_from_result(
    result: AgentRunResult,
    *,
    request_id: str,
    run_id: str,
    thread_id: str,
) -> ChatResponse:
    """Project canonical terminal state into the existing public contract."""

    understanding = ChatUnderstanding.model_validate(
        result.state.understanding.model_dump()
    )
    decision = ChatDecision.model_validate(result.state.decision.model_dump())
    state_status = result.state.task.status
    status = {
        "WAITING_USER": "waiting_user",
        "TRANSFERRED": "transferred",
        "RESOLVED": "completed",
        "CLOSED": "closed",
    }.get(state_status.value if state_status is not None else "", "decision_ready")
    handoff = (
        ChatHandoff(
            required=result.state.handoff.required,
            summary=result.state.handoff.summary,
        )
        if result.state.handoff.required or result.state.handoff.summary
        else None
    )
    return ChatResponse(
        request_id=request_id,
        run_id=run_id,
        thread_id=thread_id,
        status=status,
        final_status=state_status.value if state_status is not None else None,
        understanding=understanding,
        decision=decision,
        trace=_trace(result),
        final_reply=result.state.response.message,
        evidence=[
            ChatEvidence.model_validate(item.model_dump())
            for item in stable_evidence_items(result.state.evidence.items)
        ],
        handoff=handoff,
    )


def _observation(
    result: AgentRunResult,
    *,
    request_id: str,
    run_id: str,
    thread_id: str,
) -> EvaluationObservation:
    actions: list[AgentAction] = []
    for event in result.events:
        if event.node != "decide_action":
            continue
        try:
            action = AgentAction(event.summary)
        except ValueError:
            continue
        actions.append(action)
    tool_calls = [
        ToolCallObservation(
            tool_name=call.tool_name,
            arguments=call.arguments,
            status=call.status,
            error_code=call.error_code,
        )
        for call in result.tool_calls
    ]
    state = result.state
    terminal = state.task.status
    if terminal is None:
        raise ValueError("successful Agent result has no terminal status")
    return EvaluationObservation(
        run_id=run_id,
        request_id=request_id,
        thread_id=thread_id,
        lifecycle_status="SUCCEEDED",
        understanding=state.understanding,
        final_decision=state.decision,
        action_sequence=actions,
        tool_calls=tool_calls,
        loop=state.loop,
        evidence=list(state.evidence.items),
        handoff=state.handoff,
        terminal_status=terminal.value,
        reply_nonempty=bool(state.response.message and state.response.message.strip()),
        loop_converged=(
            terminal is not TaskStatus.ACTIVE
            and state.loop.round_count <= state.loop.max_rounds
            and state.loop.tool_call_count <= state.loop.max_tool_calls
        ),
    )


class AgentExecutionService:
    """Own one real AgentRun lifecycle for any caller of the product runtime."""

    def __init__(
        self,
        runtime: OpsAgentRuntime,
        persistence: RunPersistenceService,
        *,
        state_factory: Callable[..., OpsAgentState] | None = None,
    ) -> None:
        self._runtime = runtime
        self._persistence = persistence
        self._state_factory = state_factory or OpsAgentState

    @property
    def runtime(self) -> OpsAgentRuntime:
        return self._runtime

    async def execute(
        self,
        *,
        message: str,
        source_context: Mapping[str, JsonValue],
        request_id: str,
        thread_id: str,
    ) -> AgentExecutionResult:
        """Run the canonical kernel and atomically finalize its real run."""

        active = self._persistence.start(
            request_id=request_id,
            thread_id=thread_id,
            input_message=message,
            source_context=source_context,
        )
        try:
            state = self._state_factory(
                identity=IdentityState(
                    user_id=(
                        source_context.get("user_id")
                        if isinstance(source_context.get("user_id"), str)
                        else None
                    ),
                    site_id=(
                        source_context.get("site_id")
                        if isinstance(source_context.get("site_id"), str)
                        else None
                    ),
                    source_context=dict(source_context),
                ),
                conversation={
                    "thread_id": thread_id,
                    "original_query": message,
                    "current_query": message,
                },
            )
            result = await self._runtime.run_with_trace(state)
            response = chat_response_from_result(
                result,
                request_id=request_id,
                run_id=active.run_id,
                thread_id=thread_id,
            )
            observation = _observation(
                result,
                request_id=request_id,
                run_id=active.run_id,
                thread_id=thread_id,
            )
        except Exception as exc:
            try:
                self._persistence.fail(
                    active,
                    error_code=normalized_error_code(exc),
                    steps=safe_failure_steps(exc),
                )
            except RunPersistenceError as persistence_error:
                raise persistence_error from None
            raise AgentExecutionError(
                run_id=active.run_id,
                request_id=request_id,
                thread_id=thread_id,
                cause=exc,
            ) from exc

        # Terminal persistence remains fail-closed.  A caller only receives a
        # successful response after the real AgentRun is durable.
        try:
            persist_chat_success(self._persistence, active, response)
        except RunPersistenceError as exc:
            # The API can return the real run identity while preserving the
            # generic persistence error envelope.
            exc.__dict__["run_id"] = active.run_id
            raise
        return AgentExecutionResult(
            response=response,
            evaluation_observation=observation,
        )


__all__ = [
    "AgentExecutionError",
    "AgentExecutionResult",
    "AgentExecutionService",
    "chat_response_from_result",
]
