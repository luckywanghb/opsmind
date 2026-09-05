"""Model-driven selection of one registered typed tool."""

from __future__ import annotations

from pydantic import ValidationError

from opsmind.agent.context import build_tool_selection_context
from opsmind.agent.diagnostics import attach_structured_node_diagnostic
from opsmind.agent.prompts import (
    TOOL_SELECTION_SYSTEM_PROMPT,
    language_instruction,
)
from opsmind.agent.schemas import ToolSelectionOutput
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
from opsmind.state import OpsAgentState, ToolState
from opsmind.tools import ToolRegistry


async def select_tool(
    state: OpsAgentState,
    gateway: ModelGateway,
    tool_registry: ToolRegistry,
) -> dict[str, ToolState]:
    """Ask the model to select a registered tool and validate its arguments.

    The registry performs the only name/schema decision in Python.  No intent,
    wording, or demo identifier is inspected here.
    """

    canonical_state = OpsAgentState.model_validate(state)
    context = build_tool_selection_context(
        canonical_state,
        tool_registry.describe(),
    )
    request = ModelRequest(
        task=ModelTask.TOOL_SELECTION,
        profile=ModelProfile.CHEAP,
        messages=[
            ModelMessage(
                role=ModelRole.SYSTEM,
                content=(
                    f"{TOOL_SELECTION_SYSTEM_PROMPT}\n"
                    f"{language_instruction(canonical_state.conversation.current_query)}"
                ),
            ),
            ModelMessage(
                role=ModelRole.USER,
                content=context.model_dump_json(exclude_none=True),
            ),
        ],
        metadata={"node": "select_tool"},
    )
    try:
        structured = await gateway.invoke_structured(request, ToolSelectionOutput)
        output = ToolSelectionOutput.model_validate(structured.parsed)
    except (ModelStructuredOutputError, ModelInvocationError) as exc:
        attach_structured_node_diagnostic(
            exc,
            node="select_tool",
            expected_schema_name=ToolSelectionOutput.__name__,
            logical_profile=ModelProfile.CHEAP.value,
        )
        raise
    except ValidationError:
        error = ModelStructuredOutputError(
            "tool-selection output failed state validation"
        )
        attach_structured_node_diagnostic(
            error,
            node="select_tool",
            expected_schema_name=ToolSelectionOutput.__name__,
            logical_profile=ModelProfile.CHEAP.value,
        )
        raise error from None
    validated_call = tool_registry.validate_call(
        output.selected_tool,
        output.arguments,
    )
    return {
        "tool": ToolState(
            selected_tool=validated_call.tool_name,
            arguments=validated_call.arguments,
            expected_resolution=output.expected_resolution,
            review_summary=None,
            evidence_sufficient=None,
            recommended_action=None,
            last_result_status=None,
            last_error_code=None,
        )
    }


__all__ = ["select_tool"]
