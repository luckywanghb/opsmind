"""Action-decision Agent node."""

from __future__ import annotations

from pydantic import ValidationError

from opsmind.agent.context import build_decision_context
from opsmind.agent.prompts import ACTION_DECISION_SYSTEM_PROMPT, language_instruction
from opsmind.agent.schemas import ActionDecisionOutput
from opsmind.models import (
    ModelGateway,
    ModelMessage,
    ModelProfile,
    ModelRequest,
    ModelRole,
    ModelStructuredOutputError,
    ModelTask,
)
from opsmind.state import DecisionState, OpsAgentState


async def decide_action(
    state: OpsAgentState,
    gateway: ModelGateway,
) -> dict[str, DecisionState]:
    """Choose the next action and return only a decision update."""

    canonical_state = OpsAgentState.model_validate(state)
    context = build_decision_context(canonical_state)
    request = ModelRequest(
        task=ModelTask.ACTION_DECISION,
        profile=ModelProfile.CHEAP,
        messages=[
            ModelMessage(
                role=ModelRole.SYSTEM,
                content=(
                    f"{ACTION_DECISION_SYSTEM_PROMPT}\n"
                    f"{language_instruction(canonical_state.conversation.current_query)}"
                ),
            ),
            ModelMessage(
                role=ModelRole.USER,
                content=context.model_dump_json(exclude_none=True),
            ),
        ],
        metadata={"node": "decide_action"},
    )
    structured = await gateway.invoke_structured(request, ActionDecisionOutput)
    try:
        output = ActionDecisionOutput.model_validate(structured.parsed)
        decision = DecisionState.model_validate(output.model_dump())
    except ValidationError as exc:
        raise ModelStructuredOutputError(
            "action-decision output failed state validation"
        ) from exc
    return {"decision": decision}
