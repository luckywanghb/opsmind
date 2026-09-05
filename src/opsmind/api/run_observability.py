"""Bridge public-safe API projections into persistent Agent-run records."""

from __future__ import annotations

from opsmind.agent.errors import AgentInputError
from opsmind.agent.graph import AgentTraceEvent
from opsmind.api.schemas import ChatResponse
from opsmind.models import (
    ModelInvocationError,
    ModelProfile,
    ModelStructuredOutputError,
    ModelTask,
    StructuredNodeFailureDiagnostic,
)
from opsmind.runs import ActiveRun, RunPersistenceService, RunStep
from opsmind.state import DecisionState, EvidenceItem, HandoffState, UnderstandingState

_FAILED_NODE_TASKS = {
    "understand_request": ModelTask.REQUEST_UNDERSTANDING,
    "decide_action": ModelTask.ACTION_DECISION,
    "select_tool": ModelTask.TOOL_SELECTION,
    "review_tool_result": ModelTask.TOOL_RESULT_REVIEW,
    "generate_clarification": ModelTask.CLARIFICATION,
    "generate_response": ModelTask.RESPONSE_GENERATION,
    "generate_handoff": ModelTask.HANDOFF_GENERATION,
}


def normalized_error_code(error: Exception) -> str:
    """Map runtime exceptions to the stable public/persistence vocabulary."""

    if isinstance(error, ModelStructuredOutputError):
        return "MODEL_STRUCTURED_OUTPUT_INVALID"
    if isinstance(error, ModelInvocationError):
        return "MODEL_INVOCATION_FAILED"
    if isinstance(error, AgentInputError):
        return "INVALID_AGENT_INPUT"
    return "INTERNAL_SERVER_ERROR"


def safe_failure_steps(error: Exception) -> list[RunStep]:
    """Project only existing safe events and allowlisted failed-node identity."""

    raw_events = getattr(error, "safe_trace_events", ())
    steps = [
        RunStep(
            sequence=sequence,
            node=event.node,
            task=event.task,
            profile=event.profile,
            status=event.status,
            summary=event.summary,
        )
        for sequence, event in enumerate(raw_events)
        if isinstance(event, AgentTraceEvent)
    ]
    diagnostic = getattr(error, "diagnostic", None)
    if not isinstance(diagnostic, StructuredNodeFailureDiagnostic):
        return steps
    task = _FAILED_NODE_TASKS.get(diagnostic.node)
    if task is None:
        return steps
    try:
        profile = ModelProfile(diagnostic.logical_profile)
    except ValueError:
        return steps
    if steps and steps[-1].node == diagnostic.node and steps[-1].status == "failed":
        return steps
    steps.append(
        RunStep(
            sequence=len(steps),
            node=diagnostic.node,
            task=task,
            profile=profile,
            status="failed",
            summary=normalized_error_code(error),
        )
    )
    return steps


def persist_chat_success(
    persistence: RunPersistenceService,
    active: ActiveRun,
    response: ChatResponse,
) -> None:
    """Finalize from the typed public-safe response, never raw runtime objects."""

    persistence.succeed(
        active,
        terminal_status=response.status,
        understanding=UnderstandingState.model_validate(
            response.understanding.model_dump()
        ),
        decision=DecisionState.model_validate(response.decision.model_dump()),
        final_reply=response.final_reply,
        handoff=(
            HandoffState.model_validate(response.handoff.model_dump())
            if response.handoff is not None
            else None
        ),
        steps=[
            RunStep(sequence=sequence, **step.model_dump())
            for sequence, step in enumerate(response.trace)
        ],
        evidence=[
            EvidenceItem.model_validate(item.model_dump())
            for item in response.evidence
        ],
    )


__all__ = ["normalized_error_code", "persist_chat_success", "safe_failure_steps"]
