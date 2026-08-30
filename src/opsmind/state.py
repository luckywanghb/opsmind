"""Typed, provider-neutral state contracts for the V0.1 OpsMind agent."""

from __future__ import annotations

import math
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

# Evidence remains prompt-visible state. These key-name-agnostic budgets allow
# compact diagnostic metadata while deterministically bounding context growth.
EVIDENCE_MAX_COLLECTION_ITEMS = 50
EVIDENCE_MAX_NESTING_DEPTH = 4
EVIDENCE_MAX_STRING_LENGTH = 2_000
EVIDENCE_MAX_SERIALIZED_BYTES = 16 * 1_024
EVIDENCE_STATE_MAX_ITEMS = 50
EVIDENCE_STATE_MAX_SERIALIZED_BYTES = 64 * 1_024


def _reject_non_finite_json(value: JsonValue, path: str = "$") -> None:
    """Reject JSON numbers that cannot round-trip through standard JSON."""

    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"non-finite number at {path}")
    if isinstance(value, list):
        for index, item in enumerate(value):
            _reject_non_finite_json(item, f"{path}[{index}]")
    elif isinstance(value, dict):
        for key, item in value.items():
            _reject_non_finite_json(item, f"{path}.{key}")


def _validate_finite_json_object(
    value: dict[str, JsonValue],
) -> dict[str, JsonValue]:
    _reject_non_finite_json(value)
    return value


FiniteJsonObject = Annotated[
    dict[str, JsonValue],
    AfterValidator(_validate_finite_json_object),
]


def _validate_compact_evidence_json(
    value: JsonValue,
    *,
    path: str = "$",
    parent_depth: int = 0,
) -> None:
    """Apply recursive evidence budgets to every nested JSON value."""

    if isinstance(value, str):
        if len(value) > EVIDENCE_MAX_STRING_LENGTH:
            raise ValueError(
                f"string at {path} exceeds {EVIDENCE_MAX_STRING_LENGTH} characters"
            )
        return

    if not isinstance(value, (dict, list)):
        return

    depth = parent_depth + 1
    if depth > EVIDENCE_MAX_NESTING_DEPTH:
        raise ValueError(
            f"collection at {path} exceeds nesting depth "
            f"{EVIDENCE_MAX_NESTING_DEPTH}"
        )
    if len(value) > EVIDENCE_MAX_COLLECTION_ITEMS:
        raise ValueError(
            f"collection at {path} exceeds {EVIDENCE_MAX_COLLECTION_ITEMS} items"
        )

    if isinstance(value, dict):
        for key, item in value.items():
            if len(key) > EVIDENCE_MAX_STRING_LENGTH:
                raise ValueError(
                    f"key at {path} exceeds {EVIDENCE_MAX_STRING_LENGTH} characters"
                )
            _validate_compact_evidence_json(
                item,
                path=f"{path}.{key}",
                parent_depth=depth,
            )
    else:
        for index, item in enumerate(value):
            _validate_compact_evidence_json(
                item,
                path=f"{path}[{index}]",
                parent_depth=depth,
            )


class PrimaryIntent(StrEnum):
    """Business domain of the user's problem."""

    SYSTEM_OPERATION = "SYSTEM_OPERATION"
    BUSINESS_RULE = "BUSINESS_RULE"
    ACCESS_ISSUE = "ACCESS_ISSUE"
    WORKFLOW_ISSUE = "WORKFLOW_ISSUE"
    DATA_ISSUE = "DATA_ISSUE"
    OTHER = "OTHER"


class RequestType(StrEnum):
    """Outcome the user wants from the agent."""

    HOW_TO = "HOW_TO"
    EXPLAIN = "EXPLAIN"
    DIAGNOSE = "DIAGNOSE"
    CHECK_STATUS = "CHECK_STATUS"
    EXECUTE_CHANGE = "EXECUTE_CHANGE"
    CONTINUE_CASE = "CONTINUE_CASE"
    CONFIRM_RESOLVED = "CONFIRM_RESOLVED"
    OTHER = "OTHER"


class RiskSignal(StrEnum):
    """Model-produced advisory risk metadata."""

    NONE = "NONE"
    PRIVILEGED_CHANGE = "PRIVILEGED_CHANGE"
    BROAD_OUTAGE = "BROAD_OUTAGE"
    SECURITY_SUSPECTED = "SECURITY_SUSPECTED"
    DESTRUCTIVE_OPERATION = "DESTRUCTIVE_OPERATION"


class AgentAction(StrEnum):
    """Action selected by the action-decision model."""

    ASK_USER = "ASK_USER"
    SEARCH = "SEARCH"
    REPLY = "REPLY"
    TRANSFER_HUMAN = "TRANSFER_HUMAN"
    END_CONVERSATION = "END_CONVERSATION"


class TaskStatus(StrEnum):
    """Lifecycle status of the current task."""

    ACTIVE = "ACTIVE"
    WAITING_USER = "WAITING_USER"
    INVESTIGATING = "INVESTIGATING"
    READY_TO_REPLY = "READY_TO_REPLY"
    TRANSFERRED = "TRANSFERRED"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class ResolutionStatus(StrEnum):
    """Resolution status of the current conversation problem."""

    UNKNOWN = "UNKNOWN"
    UNRESOLVED = "UNRESOLVED"
    PARTIALLY_RESOLVED = "PARTIALLY_RESOLVED"
    RESOLVED = "RESOLVED"


class CapabilityMode(StrEnum):
    """Runtime capability boundary enforced independently of model output."""

    READ_ONLY = "READ_ONLY"


class StateModel(BaseModel):
    """Base contract that rejects undeclared state at every model boundary."""

    model_config = ConfigDict(
        extra="forbid",
        revalidate_instances="always",
        validate_assignment=True,
    )


class IdentityState(StateModel):
    """Synthetic caller identity and request source context."""

    user_id: str | None = None
    site_id: str | None = None
    department: str | None = None
    roles: list[str] = Field(default_factory=list)
    source_context: FiniteJsonObject = Field(default_factory=dict)


class ConversationState(StateModel):
    """Compact context for the current thread."""

    thread_id: str | None = None
    original_query: str | None = None
    current_query: str | None = None
    summary: str | None = None
    previous_resolution_status: ResolutionStatus | None = None


class UnderstandingState(StateModel):
    """Structured output produced by request understanding."""

    primary_intent: PrimaryIntent | None = None
    request_type: RequestType | None = None
    symptom: str | None = None
    entities: FiniteJsonObject = Field(default_factory=dict)
    risk_signal: RiskSignal = RiskSignal.NONE
    uncertainty: str | None = None


class TaskState(StateModel):
    """Compact description of the current task and its progress."""

    objective: str | None = None
    status: TaskStatus | None = None
    constraints: list[str] = Field(default_factory=list)


NonNegativeInt = Annotated[int, Field(ge=0, strict=True)]
PositiveInt = Annotated[int, Field(ge=1, strict=True)]
PositiveFloat = Annotated[
    float,
    Field(gt=0, strict=True, allow_inf_nan=False),
]


class LoopState(StateModel):
    """Harness-owned counters and convergence limits."""

    round_count: NonNegativeInt = 0
    tool_call_count: NonNegativeInt = 0
    retry_count: NonNegativeInt = 0
    max_rounds: PositiveInt = 8
    max_tool_calls: PositiveInt = 12
    max_retries: PositiveInt = 2
    tool_timeout_seconds: PositiveFloat = 30.0


class FactsState(StateModel):
    """Compact task-relevant facts and remaining questions."""

    confirmed: list[str] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)


class EvidenceItem(StateModel):
    """Compact evidence retained in state instead of a raw tool result."""

    source: str = Field(max_length=EVIDENCE_MAX_STRING_LENGTH)
    summary: str = Field(max_length=EVIDENCE_MAX_STRING_LENGTH)
    key_fields: FiniteJsonObject = Field(default_factory=dict)
    metadata: FiniteJsonObject = Field(default_factory=dict)
    artifact_ref: str | None = Field(
        default=None,
        max_length=EVIDENCE_MAX_STRING_LENGTH,
    )
    timestamp: datetime

    @field_validator("key_fields", "metadata")
    @classmethod
    def validate_compact_json(
        cls, value: dict[str, JsonValue]
    ) -> dict[str, JsonValue]:
        _validate_compact_evidence_json(value)
        return value

    @model_validator(mode="after")
    def validate_serialized_size(self) -> Self:
        serialized_size = len(self.model_dump_json().encode("utf-8"))
        if serialized_size > EVIDENCE_MAX_SERIALIZED_BYTES:
            raise ValueError(
                "evidence item exceeds "
                f"{EVIDENCE_MAX_SERIALIZED_BYTES} serialized bytes"
            )
        return self


class EvidenceState(StateModel):
    """Evidence accumulated for the current task."""

    items: list[EvidenceItem] = Field(
        default_factory=list,
        max_length=EVIDENCE_STATE_MAX_ITEMS,
    )

    @model_validator(mode="after")
    def validate_serialized_size(self) -> Self:
        serialized_size = len(self.model_dump_json().encode("utf-8"))
        if serialized_size > EVIDENCE_STATE_MAX_SERIALIZED_BYTES:
            raise ValueError(
                "evidence state exceeds "
                f"{EVIDENCE_STATE_MAX_SERIALIZED_BYTES} serialized bytes"
            )
        return self


class DecisionState(StateModel):
    """Most recent model-selected action, goal, and compact rationale."""

    action: AgentAction | None = None
    goal: str | None = None
    rationale: str | None = None


class ToolState(StateModel):
    """Current tool plan without persisted raw tool output."""

    selected_tool: str | None = None
    arguments: FiniteJsonObject = Field(default_factory=dict)
    expected_resolution: str | None = None


class SafetyState(StateModel):
    """Deterministic runtime capability and any applied safety block."""

    capability: CapabilityMode = CapabilityMode.READ_ONLY
    blocked_reason: str | None = None


class HandoffState(StateModel):
    """Information prepared for a human handoff when required."""

    required: bool = False
    summary: str | None = None


class ResponseState(StateModel):
    """Latest user-facing response produced by the model."""

    message: str | None = None
    is_final: bool = False


class OpsAgentState(StateModel):
    """Root V0.1 state contract shared by the agent harness and nodes.

    Pydantic cannot observe mutation performed inside an existing list or dict.
    Call ``OpsAgentState.model_validate(state)`` before crossing a node or
    persistence boundary; instance revalidation is enabled for that purpose.
    """

    identity: IdentityState = Field(default_factory=IdentityState)
    conversation: ConversationState = Field(default_factory=ConversationState)
    understanding: UnderstandingState = Field(default_factory=UnderstandingState)
    task: TaskState = Field(default_factory=TaskState)
    loop: LoopState = Field(default_factory=LoopState)
    facts: FactsState = Field(default_factory=FactsState)
    evidence: EvidenceState = Field(default_factory=EvidenceState)
    decision: DecisionState = Field(default_factory=DecisionState)
    tool: ToolState = Field(default_factory=ToolState)
    safety: SafetyState = Field(default_factory=SafetyState)
    handoff: HandoffState = Field(default_factory=HandoffState)
    response: ResponseState = Field(default_factory=ResponseState)
