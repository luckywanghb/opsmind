"""Typed public contracts for the OpsMind HTTP API."""

from __future__ import annotations

from typing import Literal
from unicodedata import category

from pydantic import BaseModel, ConfigDict, Field, field_validator

from opsmind.models import ModelProfile, ModelTask
from opsmind.state import (
    AgentAction,
    FiniteJsonObject,
    PrimaryIntent,
    RequestType,
    RiskSignal,
)

MAX_MESSAGE_LENGTH = 8_000
MAX_THREAD_ID_LENGTH = 128


class ApiModel(BaseModel):
    """Strict base model shared by all public API schemas."""

    model_config = ConfigDict(extra="forbid", revalidate_instances="always")


class ChatRequest(ApiModel):
    """Input accepted by ``POST /api/v1/chat``."""

    message: str = Field(min_length=1, max_length=MAX_MESSAGE_LENGTH)
    thread_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_THREAD_ID_LENGTH,
    )
    source_context: FiniteJsonObject = Field(default_factory=dict)

    @field_validator("message")
    @classmethod
    def reject_blank_message(cls, value: str) -> str:
        if not any(
            not character.isspace() and category(character) != "Cf"
            for character in value
        ):
            raise ValueError("message must not be blank")
        return value

    @field_validator("thread_id")
    @classmethod
    def reject_blank_thread_id(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("thread_id must not be blank")
        return value


class ChatUnderstanding(ApiModel):
    """Validated request understanding returned by the kernel."""

    primary_intent: PrimaryIntent
    request_type: RequestType
    symptom: str | None
    entities: FiniteJsonObject
    risk_signal: RiskSignal
    uncertainty: str | None


class ChatDecision(ApiModel):
    """Validated next-action decision returned by the kernel."""

    action: AgentAction
    goal: str
    rationale: str


class AgentTraceStep(ApiModel):
    """Safe summary of one actually completed model-backed Agent node."""

    node: str
    task: ModelTask
    profile: ModelProfile
    status: Literal["completed"] = "completed"
    summary: str


class ChatResponse(ApiModel):
    """Successful response from one complete two-node kernel run."""

    request_id: str
    thread_id: str
    status: Literal["decision_ready"] = "decision_ready"
    understanding: ChatUnderstanding
    decision: ChatDecision
    trace: list[AgentTraceStep]


class HealthResponse(ApiModel):
    """Process-level health response that does not probe model providers."""

    status: Literal["ok"] = "ok"
    service: Literal["opsmind"] = "opsmind"


class ErrorDetail(ApiModel):
    """Stable machine-readable error payload."""

    code: str
    message: str
    request_id: str


class ErrorResponse(ApiModel):
    """Unified error envelope."""

    error: ErrorDetail
