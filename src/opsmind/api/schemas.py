"""Typed public contracts for the OpsMind HTTP API."""

from __future__ import annotations

from datetime import datetime
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
    """Safe summary of one actual model or harness execution step."""

    node: str
    task: ModelTask
    profile: ModelProfile | Literal["HARNESS"]
    status: Literal["completed", "failed", "blocked"] = "completed"
    summary: str


class ChatEvidence(ApiModel):
    """Compact evidence exposed to the UI without raw adapter payloads."""

    evidence_id: str | None = None
    source: str
    summary: str
    key_fields: FiniteJsonObject = Field(default_factory=dict)
    metadata: FiniteJsonObject = Field(default_factory=dict)
    artifact_ref: str | None = None
    timestamp: datetime


class ChatHandoff(ApiModel):
    """Safe human-handoff outcome."""

    required: bool
    summary: str | None = None


class ChatResponse(ApiModel):
    """Successful response from one bounded Agent-loop run."""

    request_id: str
    thread_id: str
    status: Literal[
        "decision_ready",
        "completed",
        "waiting_user",
        "transferred",
        "closed",
    ] = "decision_ready"
    final_status: str | None = None
    understanding: ChatUnderstanding
    decision: ChatDecision
    trace: list[AgentTraceStep]
    final_reply: str | None = None
    evidence: list[ChatEvidence] = Field(default_factory=list)
    handoff: ChatHandoff | None = None


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
