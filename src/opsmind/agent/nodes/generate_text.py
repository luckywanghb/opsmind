"""Typed terminal planning and deterministic user-facing rendering nodes."""

from __future__ import annotations

from pydantic import ValidationError

from opsmind.agent.context import build_response_plan_context
from opsmind.agent.diagnostics import attach_structured_node_diagnostic
from opsmind.agent.grounding import render_grounded_response
from opsmind.agent.prompts import (
    CLARIFICATION_SYSTEM_PROMPT,
    GROUNDED_RESPONSE_PLAN_SYSTEM_PROMPT,
    HANDOFF_GENERATION_SYSTEM_PROMPT,
    language_instruction,
)
from opsmind.agent.schemas import (
    GroundedResponsePlanOutput,
    GroundedTerminalMode,
)
from opsmind.models import (
    ModelGateway,
    ModelInvocationError,
    ModelMessage,
    ModelProfile,
    ModelRequest,
    ModelRole,
    ModelStructuredOutputError,
    ModelTask,
)
from opsmind.state import HandoffState, OpsAgentState, ResponseState
from opsmind.tools import ToolRegistry


async def generate_response_plan(
    state: OpsAgentState,
    gateway: ModelGateway,
    tool_registry: ToolRegistry,
    *,
    task: ModelTask = ModelTask.GROUNDED_RESPONSE_PLAN,
    node: str = "generate_response",
    system_prompt: str = GROUNDED_RESPONSE_PLAN_SYSTEM_PROMPT,
) -> GroundedResponsePlanOutput:
    """Ask the model only for a terminal mode and evidence references.

    This structured result is transient. It is validated again against the
    actual run-local evidence immediately before rendering.
    """

    canonical_state = OpsAgentState.model_validate(state)
    context = build_response_plan_context(canonical_state, tool_registry)
    request = ModelRequest(
        task=task,
        profile=ModelProfile.CHEAP,
        messages=[
            ModelMessage(
                role=ModelRole.SYSTEM,
                content=(
                    f"{system_prompt}\n"
                    f"{language_instruction(canonical_state.conversation.current_query)}"
                ),
            ),
            ModelMessage(
                role=ModelRole.USER,
                content=context.model_dump_json(exclude_none=True),
            ),
        ],
        metadata={"node": node},
    )
    try:
        structured = await gateway.invoke_structured(
            request,
            GroundedResponsePlanOutput,
        )
        return GroundedResponsePlanOutput.model_validate(structured.parsed)
    except (ModelStructuredOutputError, ModelInvocationError) as exc:
        attach_structured_node_diagnostic(
            exc,
            node=node,
            expected_schema_name=GroundedResponsePlanOutput.__name__,
            logical_profile=ModelProfile.CHEAP.value,
        )
        raise
    except ValidationError:
        error = ModelStructuredOutputError(
            "grounded response plan failed typed validation"
        )
        attach_structured_node_diagnostic(
            error,
            node=node,
            expected_schema_name=GroundedResponsePlanOutput.__name__,
            logical_profile=ModelProfile.CHEAP.value,
        )
        raise error from None


def _render_terminal(
    state: OpsAgentState,
    plan: GroundedResponsePlanOutput,
    tool_registry: ToolRegistry,
    expected_mode: GroundedTerminalMode,
) -> str:
    """Apply the all-or-nothing evidence boundary before returning text."""

    return render_grounded_response(
        plan,
        state.evidence.items,
        tool_registry,
        expected_terminal_mode=expected_mode,
    )


async def generate_response(
    state: OpsAgentState,
    gateway: ModelGateway,
    tool_registry: ToolRegistry,
) -> dict[str, ResponseState]:
    """Generate a final reply from a validated plan and typed evidence only."""

    canonical_state = OpsAgentState.model_validate(state)
    plan = await generate_response_plan(
        canonical_state,
        gateway,
        tool_registry,
        task=ModelTask.GROUNDED_RESPONSE_PLAN,
        node="generate_response",
    )
    message = _render_terminal(
        canonical_state,
        plan,
        tool_registry,
        GroundedTerminalMode.REPLY,
    )
    return {"response": ResponseState(message=message, is_final=True)}


async def generate_clarification(
    state: OpsAgentState,
    gateway: ModelGateway,
    tool_registry: ToolRegistry,
) -> dict[str, ResponseState]:
    """Generate a deterministic clarification from a typed plan."""

    canonical_state = OpsAgentState.model_validate(state)
    plan = await generate_response_plan(
        canonical_state,
        gateway,
        tool_registry,
        task=ModelTask.CLARIFICATION,
        node="generate_clarification",
        system_prompt=(
            f"{CLARIFICATION_SYSTEM_PROMPT}\n"
            f"{GROUNDED_RESPONSE_PLAN_SYSTEM_PROMPT}"
        ),
    )
    message = _render_terminal(
        canonical_state,
        plan,
        tool_registry,
        GroundedTerminalMode.ASK_USER,
    )
    return {"response": ResponseState(message=message, is_final=False)}


async def generate_handoff(
    state: OpsAgentState,
    gateway: ModelGateway,
    tool_registry: ToolRegistry,
) -> dict[str, object]:
    """Generate a safe handoff from typed source references only."""

    canonical_state = OpsAgentState.model_validate(state)
    plan = await generate_response_plan(
        canonical_state,
        gateway,
        tool_registry,
        task=ModelTask.HANDOFF_GENERATION,
        node="generate_handoff",
        system_prompt=(
            f"{HANDOFF_GENERATION_SYSTEM_PROMPT}\n"
            f"{GROUNDED_RESPONSE_PLAN_SYSTEM_PROMPT}"
        ),
    )
    message = _render_terminal(
        canonical_state,
        plan,
        tool_registry,
        GroundedTerminalMode.TRANSFER_HUMAN,
    )
    return {
        "handoff": HandoffState(required=True, summary=message),
        "response": ResponseState(message=message, is_final=True),
    }


__all__ = [
    "generate_clarification",
    "generate_handoff",
    "generate_response",
    "generate_response_plan",
]
