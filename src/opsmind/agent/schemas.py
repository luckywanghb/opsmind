"""Node-specific structured output contracts for the minimal kernel.

These models are transient model-call contracts.  They deliberately contain
only the fields owned by their node; the node validates and maps them into the
corresponding section of the canonical :class:`OpsAgentState`.
"""

from __future__ import annotations

from pydantic import Field, field_validator

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
    symptom: str | None = None
    entities: FiniteJsonObject = Field(default_factory=dict)
    risk_signal: RiskSignal = RiskSignal.NONE
    uncertainty: str | None = None


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
