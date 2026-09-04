"""User-facing text generation nodes for terminal Agent actions."""

from __future__ import annotations

from opsmind.agent.context import build_response_context
from opsmind.agent.prompts import (
    CLARIFICATION_SYSTEM_PROMPT,
    HANDOFF_GENERATION_SYSTEM_PROMPT,
    RESPONSE_GENERATION_SYSTEM_PROMPT,
    language_instruction,
)
from opsmind.models import (
    ModelGateway,
    ModelMessage,
    ModelProfile,
    ModelRequest,
    ModelRole,
    ModelTask,
)
from opsmind.state import HandoffState, OpsAgentState, ResponseState


async def _generate_text(
    state: OpsAgentState,
    gateway: ModelGateway,
    *,
    task: ModelTask,
    node: str,
    system_prompt: str,
) -> str:
    """Generate bounded user-facing text through the provider-neutral gateway."""

    canonical_state = OpsAgentState.model_validate(state)
    context = build_response_context(canonical_state)
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
    response = await gateway.invoke(request)
    if not response.content.strip():
        # Treat empty model text as a provider failure.  The API sanitizes the
        # resulting error, while tests can distinguish this from a successful
        # but empty response.
        from opsmind.models import ModelInvocationError

        raise ModelInvocationError(f"{node} returned empty text")
    return response.content.strip()


async def generate_response(
    state: OpsAgentState,
    gateway: ModelGateway,
) -> dict[str, ResponseState]:
    """Generate a grounded final reply after a REPLY action."""

    message = await _generate_text(
        state,
        gateway,
        task=ModelTask.RESPONSE_GENERATION,
        node="generate_response",
        system_prompt=RESPONSE_GENERATION_SYSTEM_PROMPT,
    )
    return {"response": ResponseState(message=message, is_final=True)}


async def generate_clarification(
    state: OpsAgentState,
    gateway: ModelGateway,
) -> dict[str, ResponseState]:
    """Generate one clarification question; ASK_USER ends this run."""

    message = await _generate_text(
        state,
        gateway,
        task=ModelTask.CLARIFICATION,
        node="generate_clarification",
        system_prompt=CLARIFICATION_SYSTEM_PROMPT,
    )
    return {"response": ResponseState(message=message, is_final=False)}


async def generate_handoff(
    state: OpsAgentState,
    gateway: ModelGateway,
) -> dict[str, object]:
    """Generate a safe human-handoff summary."""

    message = await _generate_text(
        state,
        gateway,
        task=ModelTask.HANDOFF_GENERATION,
        node="generate_handoff",
        system_prompt=HANDOFF_GENERATION_SYSTEM_PROMPT,
    )
    return {
        "handoff": HandoffState(required=True, summary=message),
        "response": ResponseState(message=message, is_final=True),
    }


__all__ = [
    "generate_clarification",
    "generate_handoff",
    "generate_response",
]
