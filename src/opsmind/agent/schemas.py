"""Node-specific structured output contracts for the Agent loop.

These models are transient model-call contracts.  They deliberately contain
only the fields owned by their node; the node validates and maps them into the
corresponding section of the canonical :class:`OpsAgentState`.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import AliasChoices, Field, field_validator, model_validator

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
        validation_alias=AliasChoices("evidence_sufficient", "sufficient"),
        description=(
            "Whether the reviewed source facts support a useful bounded answer "
            "to the current request; true does not mean every related unknown "
            "or threshold has been resolved."
        ),
    )
    summary: Annotated[
        str,
        Field(
            min_length=1,
            description=(
                "Compact source-grounded review summary; do not infer absent fields."
            ),
        ),
    ]
    confirmed_facts: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("confirmed_facts", "facts"),
        description="Direct observations from returned fields only.",
    )
    unresolved_questions: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("unresolved_questions", "unresolved"),
        description=(
            "Material limitations to evaluate, not an automatic clarification "
            "checklist."
        ),
    )
    recommended_action: AgentAction = Field(
        validation_alias=AliasChoices(
            "recommended_action", "next_action", "action"
        ),
        description=(
            "Advisory review recommendation; the fresh action-decision model "
            "remains authoritative."
        ),
    )

    @field_validator("summary")
    @classmethod
    def reject_blank_summary(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("summary must not be blank")
        return value


class GroundedTerminalMode(StrEnum):
    """Terminal modes accepted by a grounded response plan."""

    REPLY = "REPLY"
    ASK_USER = "ASK_USER"
    TRANSFER_HUMAN = "TRANSFER_HUMAN"
    END_CONVERSATION = "END_CONVERSATION"


class ResponsePresentationIntent(StrEnum):
    """Small, non-factual vocabulary for deterministic presentation."""

    FACTS = "FACTS"
    FACT_SUMMARY = "FACT_SUMMARY"
    FACTS_WITH_LIMITATION = "FACTS_WITH_LIMITATION"
    LIMITED_FACTS = "LIMITED_FACTS"
    NOT_FOUND = "NOT_FOUND"
    CLARIFICATION = "CLARIFICATION"
    HANDOFF = "HANDOFF"
    CLOSE = "CLOSE"


class GroundingLimitation(StrEnum):
    """Bounded limitation templates available to a response plan."""

    NONE = "NONE"
    CAUSE_UNAVAILABLE = "CAUSE_UNAVAILABLE"
    THRESHOLD_UNAVAILABLE = "THRESHOLD_UNAVAILABLE"
    ENTITLEMENT_UNAVAILABLE = "ENTITLEMENT_UNAVAILABLE"
    REMEDIATION_UNAVAILABLE = "REMEDIATION_UNAVAILABLE"
    MATCH_UNAVAILABLE = "MATCH_UNAVAILABLE"
    SCOPE_UNAVAILABLE = "SCOPE_UNAVAILABLE"
    EVIDENCE_INSUFFICIENT = "EVIDENCE_INSUFFICIENT"
    MISSING_CAUSE = "MISSING_CAUSE"
    MISSING_THRESHOLD = "MISSING_THRESHOLD"


class ClarificationTarget(StrEnum):
    """Safe fixed targets for a model-selected clarification prompt."""

    GENERIC = "GENERIC"
    IDENTIFIER = "IDENTIFIER"
    USER_ID = "USER_ID"
    SYSTEM_ID = "SYSTEM_ID"
    SITE = "SITE"
    SCOPE = "SCOPE"


class EvidenceReference(StateModel):
    """Reference to one field in one run-local compact evidence item.

    The reference carries no value or prose.  The harness resolves both the
    evidence ID and canonical field path against the typed tool response before
    a renderer can use it.
    """

    evidence_id: str = Field(
        min_length=2,
        max_length=7,
        pattern=r"^E[1-9][0-9]{0,5}$",
        validation_alias=AliasChoices("evidence_id", "evidenceID", "id"),
    )
    path: str = Field(
        min_length=1,
        max_length=200,
        validation_alias=AliasChoices("path", "field_path", "field"),
    )

    @field_validator("path")
    @classmethod
    def reject_invalid_path_text(cls, value: str) -> str:
        if not value.strip() or any(character.isspace() for character in value):
            raise ValueError("evidence path must be a non-blank token")
        if ".." in value or value.startswith("/") or value.endswith("/"):
            raise ValueError("evidence path must be canonical")
        return value


class GroundedResponsePlanOutput(StateModel):
    """Transient model output consumed by the deterministic final renderer.

    There is intentionally no ``message``, ``claim``, ``answer`` or other
    free-form factual field.  The model selects a terminal/presentation intent
    and relevant references; values and limitation wording are supplied by
    typed evidence contracts and fixed renderer templates.
    """

    terminal_mode: GroundedTerminalMode = Field(
        validation_alias=AliasChoices(
            "terminal_mode",
            "terminal_action",
            "terminal",
            "terminal_intent",
            "action",
            "mode",
        )
    )
    presentation_intent: ResponsePresentationIntent = Field(
        validation_alias=AliasChoices(
            "presentation_intent",
            "presentation",
            "intent",
        )
    )
    evidence_references: list[EvidenceReference] = Field(
        default_factory=list,
        max_length=50,
        validation_alias=AliasChoices(
            "evidence_references",
            "evidence_refs",
            "references",
            "refs",
            "evidence",
        ),
    )
    limitation: GroundingLimitation = Field(
        default=GroundingLimitation.NONE,
        validation_alias=AliasChoices("limitation", "limitation_kind"),
    )
    clarification_target: ClarificationTarget = ClarificationTarget.GENERIC

    @model_validator(mode="after")
    def validate_terminal_presentation(self) -> GroundedResponsePlanOutput:
        if (
            self.terminal_mode is GroundedTerminalMode.END_CONVERSATION
            and self.evidence_references
        ):
            raise ValueError("END_CONVERSATION response plans cannot cite evidence")
        if (
            self.terminal_mode is GroundedTerminalMode.ASK_USER
            and self.presentation_intent is ResponsePresentationIntent.HANDOFF
        ):
            raise ValueError("ASK_USER plans cannot use HANDOFF presentation")
        if (
            self.terminal_mode is GroundedTerminalMode.TRANSFER_HUMAN
            and self.presentation_intent is ResponsePresentationIntent.CLARIFICATION
        ):
            raise ValueError(
                "TRANSFER_HUMAN plans cannot use CLARIFICATION presentation"
            )
        return self


__all__ = [
    "ActionDecisionOutput",
    "ClarificationTarget",
    "EvidenceReference",
    "GroundedResponsePlanOutput",
    "GroundedTerminalMode",
    "GroundingLimitation",
    "RequestUnderstandingOutput",
    "ResponsePresentationIntent",
    "ToolResultReviewOutput",
    "ToolSelectionOutput",
]
