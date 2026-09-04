"""Node-specific structured output contracts for the Agent loop.

These models are transient model-call contracts.  They deliberately contain
only the fields owned by their node; the node validates and maps them into the
corresponding section of the canonical :class:`OpsAgentState`.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import AliasChoices, Field, field_validator

from opsmind.state import (
    AgentAction,
    FiniteJsonObject,
    PrimaryIntent,
    RequestType,
    RiskSignal,
    StateModel,
)


class RequestUnderstandingOutput(StateModel):
    """Structured output owned by the request-understanding node."""

    primary_intent: PrimaryIntent
    request_type: RequestType
    symptom: str | None
    entities: FiniteJsonObject
    risk_signal: RiskSignal
    uncertainty: str | None


class ActionDecisionOutput(StateModel):
    """Structured output owned by the action-decision node."""

    action: AgentAction
    goal: str = Field(min_length=1)
    rationale: str = Field(min_length=1)

    @field_validator("goal", "rationale")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must not be blank")
        return value


class ToolSelectionOutput(StateModel):
    """Model-selected registered tool and arguments.

    ``arguments`` is validated again against the selected tool's concrete
    request model by the harness.  It is a transient envelope, not a tool
    contract; concrete request/response schemas live in ``opsmind.tools``.
    """

    selected_tool: Annotated[str, Field(min_length=1)] = Field(
        validation_alias=AliasChoices("selected_tool", "tool_name")
    )
    arguments: FiniteJsonObject
    expected_resolution: Annotated[str | None, Field(min_length=1)] = Field(
        default=None,
        validation_alias=AliasChoices("expected_resolution", "goal", "reason")
    )

    @field_validator("selected_tool", "expected_resolution")
    @classmethod
    def reject_blank_selection_text(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("value must not be blank")
        return value


class ToolResultReviewOutput(StateModel):
    """Model interpretation of one typed tool result.

    The recommendation is advisory: the graph performs a fresh action-decision
    model call after this node.  That re-decision prevents Python from turning
    one business scenario into a hidden branch.
    """

    evidence_sufficient: bool = Field(
        validation_alias=AliasChoices("evidence_sufficient", "sufficient")
    )
    summary: Annotated[str, Field(min_length=1)]
    confirmed_facts: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("confirmed_facts", "facts"),
    )
    unresolved_questions: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("unresolved_questions", "unresolved"),
    )
    recommended_action: AgentAction = Field(
        validation_alias=AliasChoices(
            "recommended_action", "next_action", "action"
        )
    )

    @field_validator("summary")
    @classmethod
    def reject_blank_summary(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("summary must not be blank")
        return value


__all__ = [
    "ActionDecisionOutput",
    "RequestUnderstandingOutput",
    "ToolResultReviewOutput",
    "ToolSelectionOutput",
]
