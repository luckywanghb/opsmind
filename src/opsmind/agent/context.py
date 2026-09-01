"""Explicit, node-specific context assembly for model calls."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime

from pydantic import Field

from opsmind.agent.errors import AgentInputError
from opsmind.state import (
    EvidenceItem,
    FactsState,
    FiniteJsonObject,
    LoopState,
    OpsAgentState,
    ResolutionStatus,
    StateModel,
    TaskState,
    TaskStatus,
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
    loop: DecisionLoopContext


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


def _loop_context(loop: LoopState) -> DecisionLoopContext:
    return DecisionLoopContext(
        round_count=loop.round_count,
        tool_call_count=loop.tool_call_count,
        retry_count=loop.retry_count,
        max_rounds=loop.max_rounds,
        max_tool_calls=loop.max_tool_calls,
        max_retries=loop.max_retries,
    )


def build_decision_context(state: OpsAgentState) -> DecisionContext:
    """Select the compact state projection needed for action decision."""

    canonical_state = _validated_state(state)
    query = _current_query(canonical_state)
    return DecisionContext(
        current_query=query,
        understanding=canonical_state.understanding.model_copy(deep=True),
        task=_task_context(canonical_state.task),
        facts=_facts_context(canonical_state.facts),
        evidence=[_evidence_summary(item) for item in canonical_state.evidence.items],
        loop=_loop_context(canonical_state.loop),
    )
