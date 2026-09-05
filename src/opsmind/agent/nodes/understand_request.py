"""Request-understanding Agent node."""

from __future__ import annotations

from pydantic import ValidationError

from opsmind.agent.context import build_understanding_context
from opsmind.agent.diagnostics import attach_structured_node_diagnostic
from opsmind.agent.prompts import (
    REQUEST_UNDERSTANDING_SYSTEM_PROMPT,
    language_instruction,
)
from opsmind.agent.schemas import RequestUnderstandingOutput
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
from opsmind.state import OpsAgentState, UnderstandingState


async def understand_request(
    state: OpsAgentState,
    gateway: ModelGateway,
) -> dict[str, UnderstandingState]:
    """Understand the current query and return only an understanding update."""

    canonical_state = OpsAgentState.model_validate(state)
    context = build_understanding_context(canonical_state)
    request = ModelRequest(
        task=ModelTask.REQUEST_UNDERSTANDING,
        profile=ModelProfile.CHEAP,
        messages=[
            ModelMessage(
                role=ModelRole.SYSTEM,
                content=(
                    f"{REQUEST_UNDERSTANDING_SYSTEM_PROMPT}\n"
                    f"{language_instruction(canonical_state.conversation.current_query)}"
                ),
            ),
            ModelMessage(
                role=ModelRole.USER,
                content=context.model_dump_json(exclude_none=True),
            ),
        ],
        metadata={"node": "understand_request"},
    )
    try:
        structured = await gateway.invoke_structured(
            request,
            RequestUnderstandingOutput,
        )
        output = RequestUnderstandingOutput.model_validate(structured.parsed)
        understanding = UnderstandingState.model_validate(output.model_dump())
    except (ModelStructuredOutputError, ModelInvocationError) as exc:
        attach_structured_node_diagnostic(
            exc,
            node="understand_request",
            expected_schema_name=RequestUnderstandingOutput.__name__,
            logical_profile=ModelProfile.CHEAP.value,
        )
        raise
    except ValidationError:
        error = ModelStructuredOutputError(
            "request-understanding output failed state validation"
        )
        attach_structured_node_diagnostic(
            error,
            node="understand_request",
            expected_schema_name=RequestUnderstandingOutput.__name__,
            logical_profile=ModelProfile.CHEAP.value,
        )
        raise error from None
    return {"understanding": understanding}
