"""Explicit, node-specific context assembly for model calls."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any

from pydantic import Field

from opsmind.agent.errors import AgentInputError
from opsmind.state import (
    AgentAction,
    DecisionState,
    EvidenceItem,
    FactsState,
    FiniteJsonObject,
    LoopState,
    OpsAgentState,
    ResolutionStatus,
    StateModel,
    TaskState,
    TaskStatus,
    ToolState,
    UnderstandingState,
)


class UnderstandingContext(StateModel):
    """Conversation and source information needed to understand a request."""

    current_query: str
    original_query: str | None = None
    summary: str | None = None
    previous_resolution_status: ResolutionStatus | None = None
    source_context: FiniteJsonObject = Field(default_factory=dict)


class DecisionTaskContext(StateModel):
    """Task fields relevant to selecting the next action."""

    objective: str | None = None
    status: TaskStatus | None = None
    constraints: list[str] = Field(default_factory=list)


class DecisionFactsContext(StateModel):
    """Confirmed facts and unresolved questions for action selection."""

    confirmed: list[str] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)


class DecisionLoopContext(StateModel):
    """Loop counters and limits relevant to a bounded action decision."""

    round_count: int
    tool_call_count: int
    retry_count: int
    max_rounds: int
    max_tool_calls: int
    max_retries: int


class LatestReviewContext(StateModel):
    """Compact advisory output from the most recent tool-result review."""

    selected_tool: str | None = None
    expected_resolution: str | None = None
    review_summary: str | None = None
    evidence_sufficient: bool | None = None
    recommended_action: AgentAction | None = None
    result_status: str | None = None
    error_code: str | None = None


class ToolCapabilityContext(StateModel):
    """Bounded metadata for capabilities available in this graph run."""

    name: str
    description: str
    mode: str
    output_schema: FiniteJsonObject | None = None


class EvidenceSummaryContext(StateModel):
    """Compact evidence projection; raw tool results never enter context."""

    source: str
    summary: str
    key_fields: FiniteJsonObject = Field(default_factory=dict)
    artifact_ref: str | None = None
    timestamp: datetime


class DecisionContext(StateModel):
    """State projection visible to the action-decision model."""

    current_query: str
    understanding: UnderstandingState
    task: DecisionTaskContext
    facts: DecisionFactsContext
    evidence: list[EvidenceSummaryContext] = Field(default_factory=list)
    latest_review: LatestReviewContext
    available_tools: list[ToolCapabilityContext] = Field(default_factory=list)
    loop: DecisionLoopContext


class ToolIdentityContext(StateModel):
    """Identity fields that can help extract typed tool arguments."""

    user_id: str | None = None
    site_id: str | None = None


class ToolSelectionContext(StateModel):
    """Compact context visible to the model selecting a registered tool."""

    current_query: str
    understanding: UnderstandingState
    decision: DecisionState
    identity: ToolIdentityContext
    evidence: list[EvidenceSummaryContext] = Field(default_factory=list)
    available_tools: list[dict[str, Any]] = Field(default_factory=list)
    loop: DecisionLoopContext


class ToolReviewContext(StateModel):
    """Typed result projection sent to the result-review model."""

    current_query: str
    task: DecisionTaskContext
    decision: DecisionState
    selected_tool: str
    arguments: FiniteJsonObject
    expected_resolution: str | None = None
    result: FiniteJsonObject
    available_tools: list[ToolCapabilityContext] = Field(default_factory=list)
    selected_tool_schema: FiniteJsonObject = Field(default_factory=dict)
    prior_evidence: list[EvidenceSummaryContext] = Field(default_factory=list)
    error_code: str | None = None


class ResponseContext(StateModel):
    """Compact grounding context for final/clarification/handoff text."""

    current_query: str
    understanding: UnderstandingState
    decision: DecisionState
    facts: DecisionFactsContext
    evidence: list[EvidenceSummaryContext] = Field(default_factory=list)
    latest_review: LatestReviewContext
    available_tools: list[ToolCapabilityContext] = Field(default_factory=list)
    handoff_required: bool = False
    safety_capability: str


def _validated_state(state: OpsAgentState) -> OpsAgentState:
    """Revalidate and detach the canonical state at a node boundary."""

    return OpsAgentState.model_validate(state)


def _current_query(state: OpsAgentState) -> str:
    """Return a required current query or fail before model invocation."""

    query = state.conversation.current_query
    if query is None or not query.strip():
        raise AgentInputError("conversation.current_query must not be blank")
    return query


def build_understanding_context(state: OpsAgentState) -> UnderstandingContext:
    """Select only conversation fields needed by request understanding."""

    canonical_state = _validated_state(state)
    query = _current_query(canonical_state)
    return UnderstandingContext(
        current_query=query,
        original_query=canonical_state.conversation.original_query,
        summary=canonical_state.conversation.summary,
        previous_resolution_status=(
            canonical_state.conversation.previous_resolution_status
        ),
        source_context=deepcopy(canonical_state.identity.source_context),
    )


def _evidence_summary(item: EvidenceItem) -> EvidenceSummaryContext:
    """Project one bounded evidence item without raw payload fields."""

    return EvidenceSummaryContext(
        source=item.source,
        summary=item.summary,
        key_fields=deepcopy(item.key_fields),
        artifact_ref=item.artifact_ref,
        timestamp=item.timestamp,
    )


def _task_context(task: TaskState) -> DecisionTaskContext:
    return DecisionTaskContext(
        objective=task.objective,
        status=task.status,
        constraints=list(task.constraints),
    )


def _facts_context(facts: FactsState) -> DecisionFactsContext:
    return DecisionFactsContext(
        confirmed=list(facts.confirmed),
        unresolved_questions=list(facts.unresolved_questions),
    )


def _latest_review_context(tool: ToolState) -> LatestReviewContext:
    """Project review fields without retaining any raw adapter output."""

    return LatestReviewContext(
        selected_tool=tool.selected_tool,
        expected_resolution=tool.expected_resolution,
        review_summary=tool.review_summary,
        evidence_sufficient=tool.evidence_sufficient,
        recommended_action=tool.recommended_action,
        result_status=tool.last_result_status,
        error_code=tool.last_error_code,
    )


def _capability_context(
    available_tools: list[dict[str, Any]],
) -> list[ToolCapabilityContext]:
    """Validate and detach run-local capability metadata."""

    return [
        ToolCapabilityContext.model_validate(deepcopy(item))
        for item in available_tools
    ]


def _loop_context(loop: LoopState) -> DecisionLoopContext:
    return DecisionLoopContext(
        round_count=loop.round_count,
        tool_call_count=loop.tool_call_count,
        retry_count=loop.retry_count,
        max_rounds=loop.max_rounds,
        max_tool_calls=loop.max_tool_calls,
        max_retries=loop.max_retries,
    )


def build_decision_context(
    state: OpsAgentState,
    available_tools: list[dict[str, Any]],
) -> DecisionContext:
    """Select the compact state projection needed for action decision."""

    canonical_state = _validated_state(state)
    query = _current_query(canonical_state)
    return DecisionContext(
        current_query=query,
        understanding=canonical_state.understanding.model_copy(deep=True),
        task=_task_context(canonical_state.task),
        facts=_facts_context(canonical_state.facts),
        evidence=[_evidence_summary(item) for item in canonical_state.evidence.items],
        latest_review=_latest_review_context(canonical_state.tool),
        available_tools=_capability_context(available_tools),
        loop=_loop_context(canonical_state.loop),
    )


def build_tool_selection_context(
    state: OpsAgentState,
    available_tools: list[dict[str, Any]],
) -> ToolSelectionContext:
    """Project only fields required for generic model-driven tool selection."""

    canonical_state = _validated_state(state)
    query = _current_query(canonical_state)
    identity = ToolIdentityContext(
        user_id=canonical_state.identity.user_id,
        site_id=canonical_state.identity.site_id,
    )
    return ToolSelectionContext(
        current_query=query,
        understanding=canonical_state.understanding.model_copy(deep=True),
        decision=canonical_state.decision.model_copy(deep=True),
        identity=identity,
        evidence=[_evidence_summary(item) for item in canonical_state.evidence.items],
        available_tools=deepcopy(available_tools),
        loop=_loop_context(canonical_state.loop),
    )


def build_tool_review_context(
    state: OpsAgentState,
    *,
    result: FiniteJsonObject,
    available_tools: list[dict[str, Any]],
    selected_tool_schema: FiniteJsonObject,
    error_code: str | None = None,
) -> ToolReviewContext:
    """Build a detached, typed result projection for one review call."""

    canonical_state = _validated_state(state)
    query = _current_query(canonical_state)
    selected_tool = canonical_state.tool.selected_tool
    if not selected_tool:
        raise AgentInputError("tool.selected_tool is required for result review")
    return ToolReviewContext(
        current_query=query,
        task=_task_context(canonical_state.task),
        decision=canonical_state.decision.model_copy(deep=True),
        selected_tool=selected_tool,
        arguments=deepcopy(canonical_state.tool.arguments),
        expected_resolution=canonical_state.tool.expected_resolution,
        result=deepcopy(result),
        available_tools=_capability_context(available_tools),
        selected_tool_schema=deepcopy(selected_tool_schema),
        prior_evidence=[
            _evidence_summary(item) for item in canonical_state.evidence.items
        ],
        error_code=error_code,
    )


def build_response_context(
    state: OpsAgentState,
    available_tools: list[dict[str, Any]],
) -> ResponseContext:
    """Build compact grounding context for user-facing text generation."""

    canonical_state = _validated_state(state)
    query = _current_query(canonical_state)
    return ResponseContext(
        current_query=query,
        understanding=canonical_state.understanding.model_copy(deep=True),
        decision=canonical_state.decision.model_copy(deep=True),
        facts=_facts_context(canonical_state.facts),
        evidence=[_evidence_summary(item) for item in canonical_state.evidence.items],
        latest_review=_latest_review_context(canonical_state.tool),
        available_tools=_capability_context(available_tools),
        handoff_required=canonical_state.handoff.required,
        safety_capability=canonical_state.safety.capability.value,
    )


__all__ = [
    "DecisionContext",
    "DecisionFactsContext",
    "DecisionLoopContext",
    "DecisionTaskContext",
    "EvidenceSummaryContext",
    "LatestReviewContext",
    "ResponseContext",
    "ToolCapabilityContext",
    "ToolIdentityContext",
    "ToolReviewContext",
    "ToolSelectionContext",
    "UnderstandingContext",
    "build_decision_context",
    "build_response_context",
    "build_tool_review_context",
    "build_tool_selection_context",
    "build_understanding_context",
]
