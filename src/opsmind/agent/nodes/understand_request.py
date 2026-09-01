"""Request-understanding Agent node."""

from __future__ import annotations

from pydantic import ValidationError

from opsmind.agent.context import build_understanding_context
from opsmind.agent.prompts import REQUEST_UNDERSTANDING_SYSTEM_PROMPT
from opsmind.agent.schemas import RequestUnderstandingOutput
from opsmind.models import (
    ModelGateway,
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
                content=REQUEST_UNDERSTANDING_SYSTEM_PROMPT,
            ),
            ModelMessage(
                role=ModelRole.USER,
                content=context.model_dump_json(exclude_none=True),
            ),
        ],
        metadata={"node": "understand_request"},
    )
    structured = await gateway.invoke_structured(request, RequestUnderstandingOutput)
    try:
        output = RequestUnderstandingOutput.model_validate(structured.parsed)
        understanding = UnderstandingState.model_validate(output.model_dump())
    except ValidationError as exc:
        raise ModelStructuredOutputError(
            "request-understanding output failed state validation"
        ) from exc
    return {"understanding": understanding}
