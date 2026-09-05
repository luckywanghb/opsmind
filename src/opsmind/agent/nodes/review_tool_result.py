"""Model-backed review and compact evidence projection for tool results."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import cast

from pydantic import JsonValue, ValidationError

from opsmind.agent.context import build_tool_review_context
from opsmind.agent.diagnostics import attach_structured_node_diagnostic
from opsmind.agent.prompts import (
    TOOL_RESULT_REVIEW_SYSTEM_PROMPT,
    language_instruction,
)
from opsmind.agent.schemas import ToolResultReviewOutput
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
from opsmind.state import EvidenceItem, FactsState, OpsAgentState, ToolState
from opsmind.tools import ToolInvocationResult, ToolRegistry

_MAX_COMPACT_TEXT = 2_000
_MAX_FACTS = 50


def _compact_text(value: str, *, limit: int = _MAX_COMPACT_TEXT) -> str:
    """Bound model-provided text before it can enter canonical state."""

    clean = value.strip()
    return clean if len(clean) <= limit else f"{clean[: limit - 1]}…"


def _compact_facts(values: Iterable[str]) -> list[str]:
    return [
        _compact_text(value)
        for value in list(values)[:_MAX_FACTS]
        if isinstance(value, str) and value.strip()
    ]


def _result_payload(execution: ToolInvocationResult) -> dict[str, JsonValue]:
    if execution.output is None:
        return {
            "result_status": "insufficient_evidence",
            "tool_name": execution.tool_name,
        }
    payload = cast(dict[str, JsonValue], execution.output.model_dump(mode="json"))
    # ``message`` is an adapter-facing presentation field, not evidence.  The
    # typed status and domain fields are enough for review and keep this
    # projection from becoming a raw response echo in long-lived state.
    payload.pop("message", None)
    return payload


async def review_tool_result(
    state: OpsAgentState,
    gateway: ModelGateway,
    execution: ToolInvocationResult,
    tool_registry: ToolRegistry,
) -> dict[str, object]:
    """Review one transient tool result and retain only compact evidence.

    ``execution.output`` is deliberately consumed here and never assigned to
    ``OpsAgentState``.  The returned update contains the typed review summary,
    facts and a small evidence item only.
    """

    canonical_state = OpsAgentState.model_validate(state)
    payload = _result_payload(execution)
    selected_tool_schema = cast(
        dict[str, JsonValue],
        tool_registry.describe_for_review(execution.tool_name)["output_schema"],
    )
    context = build_tool_review_context(
        canonical_state,
        result=payload,
        available_tools=tool_registry.describe_capabilities(),
        selected_tool_schema=selected_tool_schema,
        error_code=execution.error_code,
    )
    request = ModelRequest(
        task=ModelTask.TOOL_RESULT_REVIEW,
        profile=ModelProfile.CHEAP,
        messages=[
            ModelMessage(
                role=ModelRole.SYSTEM,
                content=(
                    f"{TOOL_RESULT_REVIEW_SYSTEM_PROMPT}\n"
                    f"{language_instruction(canonical_state.conversation.current_query)}"
                ),
            ),
            ModelMessage(
                role=ModelRole.USER,
                content=context.model_dump_json(exclude_none=True),
            ),
        ],
        metadata={"node": "review_tool_result"},
    )
    try:
        structured = await gateway.invoke_structured(
            request,
            ToolResultReviewOutput,
        )
        output = ToolResultReviewOutput.model_validate(structured.parsed)
    except (ModelStructuredOutputError, ModelInvocationError) as exc:
        attach_structured_node_diagnostic(
            exc,
            node="review_tool_result",
            expected_schema_name=ToolResultReviewOutput.__name__,
            logical_profile=ModelProfile.CHEAP.value,
        )
        raise
    except ValidationError:
        error = ModelStructuredOutputError(
            "tool-result-review output failed state validation"
        )
        attach_structured_node_diagnostic(
            error,
            node="review_tool_result",
            expected_schema_name=ToolResultReviewOutput.__name__,
            logical_profile=ModelProfile.CHEAP.value,
        )
        raise error from None

    summary = _compact_text(output.summary)
    confirmed = _compact_facts(output.confirmed_facts)
    unresolved = _compact_facts(output.unresolved_questions)
    evidence = EvidenceItem(
        source=execution.tool_name,
        summary=summary,
        key_fields=payload,
        metadata={
            "result_status": execution.status,
            "reviewed": True,
        },
        timestamp=datetime.now(UTC),
    )
    current_facts = canonical_state.facts
    facts = FactsState(
        confirmed=(current_facts.confirmed + confirmed)[-_MAX_FACTS:],
        unresolved_questions=(
            current_facts.unresolved_questions + unresolved
        )[-_MAX_FACTS:],
    )
    tool_payload = canonical_state.tool.model_dump()
    tool_payload.update(
        {
            "review_summary": summary,
            "evidence_sufficient": output.evidence_sufficient,
            "recommended_action": output.recommended_action,
            "last_result_status": execution.status,
            "last_error_code": execution.error_code,
        }
    )
    tool = ToolState.model_validate(tool_payload)
    return {
        "tool": tool,
        "facts": facts,
        "evidence": {"items": (canonical_state.evidence.items + [evidence])[-50:]},
    }


__all__ = ["review_tool_result"]
