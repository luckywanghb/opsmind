"""Action-decision Agent node."""

from __future__ import annotations

from pydantic import ValidationError

from opsmind.agent.context import build_decision_context
from opsmind.agent.diagnostics import attach_structured_node_diagnostic
from opsmind.agent.prompts import ACTION_DECISION_SYSTEM_PROMPT, language_instruction
from opsmind.agent.schemas import ActionDecisionOutput
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
from opsmind.state import DecisionState, OpsAgentState
from opsmind.tools import ToolRegistry


async def decide_action(
    state: OpsAgentState,
    gateway: ModelGateway,
    tool_registry: ToolRegistry,
) -> dict[str, DecisionState]:
    """Choose the next action and return only a decision update."""

    canonical_state = OpsAgentState.model_validate(state)
    context = build_decision_context(
        canonical_state,
        tool_registry.describe_capabilities(),
    )
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
    try:
        structured = await gateway.invoke_structured(request, ActionDecisionOutput)
        output = ActionDecisionOutput.model_validate(structured.parsed)
        decision = DecisionState.model_validate(output.model_dump())
    except (ModelStructuredOutputError, ModelInvocationError) as exc:
        attach_structured_node_diagnostic(
            exc,
            node="decide_action",
            expected_schema_name=ActionDecisionOutput.__name__,
            logical_profile=ModelProfile.CHEAP.value,
        )
        raise
    except ValidationError:
        error = ModelStructuredOutputError(
            "action-decision output failed state validation"
        )
        attach_structured_node_diagnostic(
            error,
            node="decide_action",
            expected_schema_name=ActionDecisionOutput.__name__,
            logical_profile=ModelProfile.CHEAP.value,
        )
        raise error from None
    return {"decision": decision}
