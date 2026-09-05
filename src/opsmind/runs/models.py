"""Typed domain records for one auditable Agent execution."""

from __future__ import annotations

import math
from datetime import datetime
from enum import StrEnum
from typing import Literal, Self

from pydantic import ConfigDict, Field, field_validator, model_validator

from opsmind.models import ModelProfile, ModelTask
from opsmind.state import (
    DecisionState,
    EvidenceItem,
    HandoffState,
    StateModel,
    UnderstandingState,
)

MAX_RUN_ERROR_CODE_LENGTH = 128
MAX_RUN_ID_LENGTH = 128
MAX_RUN_METADATA_VALUE_LENGTH = 256
MAX_SAFE_CONTEXT_VALUE_LENGTH = 512
MAX_TRACE_NODE_LENGTH = 128
MAX_TRACE_SUMMARY_LENGTH = 500


class RunLifecycleStatus(StrEnum):
    """Persistence lifecycle, independent from the Agent business terminal."""

    STARTED = "STARTED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


AgentTerminalStatus = Literal[
    "decision_ready",
    "completed",
    "waiting_user",
    "transferred",
    "closed",
]
RunStepStatus = Literal["completed", "failed", "blocked"]
RunStepProfile = ModelProfile | Literal["HARNESS"]


class RunModel(StateModel):
    """Strict, immutable-at-rest base for persistence domain records."""

    model_config = ConfigDict(
        extra="forbid",
        revalidate_instances="always",
        validate_assignment=True,
        frozen=True,
    )


class SafeSourceContext(RunModel):
    """Explicit allowlist of request context fields safe for long-term storage."""

    channel: str | None = Field(default=None, max_length=MAX_SAFE_CONTEXT_VALUE_LENGTH)
    user_id: str | None = Field(default=None, max_length=MAX_SAFE_CONTEXT_VALUE_LENGTH)
    site_id: str | None = Field(default=None, max_length=MAX_SAFE_CONTEXT_VALUE_LENGTH)


class RuntimeMetadata(RunModel):
    """Only runtime identity that the current application can establish."""

    app_version: str = Field(min_length=1, max_length=MAX_RUN_METADATA_VALUE_LENGTH)
    build_sha: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_RUN_METADATA_VALUE_LENGTH,
    )
    logical_model_profiles: list[ModelProfile] = Field(default_factory=list)

    @field_validator("logical_model_profiles")
    @classmethod
    def reject_duplicate_profiles(
        cls,
        value: list[ModelProfile],
    ) -> list[ModelProfile]:
        if len(value) != len(set(value)):
            raise ValueError("logical model profiles must be unique")
        return value


class RunStep(RunModel):
    """One ordered P1-006 safe-trace event, never a raw execution payload."""

    sequence: int = Field(ge=0, strict=True)
    node: str = Field(min_length=1, max_length=MAX_TRACE_NODE_LENGTH)
    task: ModelTask
    profile: RunStepProfile
    status: RunStepStatus
    summary: str = Field(max_length=MAX_TRACE_SUMMARY_LENGTH)


class AgentRunSummary(RunModel):
    """Bounded list projection for run discovery."""

    run_id: str = Field(min_length=1, max_length=MAX_RUN_ID_LENGTH)
    request_id: str = Field(min_length=1, max_length=MAX_RUN_ID_LENGTH)
    thread_id: str = Field(min_length=1, max_length=MAX_RUN_ID_LENGTH)
    lifecycle_status: RunLifecycleStatus
    agent_terminal_status: AgentTerminalStatus | None = None
    started_at: datetime
    completed_at: datetime | None = None
    duration_ms: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    error_code: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_RUN_ERROR_CODE_LENGTH,
    )

    @model_validator(mode="after")
    def validate_lifecycle_shape(self) -> Self:
        if self.started_at.tzinfo is None:
            raise ValueError("started_at must be timezone-aware")
        if self.completed_at is not None and self.completed_at.tzinfo is None:
            raise ValueError("completed_at must be timezone-aware")
        if self.duration_ms is not None and not math.isfinite(self.duration_ms):
            raise ValueError("duration_ms must be finite")
        if self.lifecycle_status is RunLifecycleStatus.STARTED:
            if any(
                value is not None
                for value in (
                    self.agent_terminal_status,
                    self.completed_at,
                    self.duration_ms,
                    self.error_code,
                )
            ):
                raise ValueError("STARTED run cannot contain terminal fields")
        elif self.completed_at is None or self.duration_ms is None:
            raise ValueError("terminal run requires completion timing")
        if self.lifecycle_status is RunLifecycleStatus.SUCCEEDED:
            if self.agent_terminal_status is None or self.error_code is not None:
                raise ValueError("SUCCEEDED run requires terminal status only")
        if self.lifecycle_status is RunLifecycleStatus.FAILED:
            if self.agent_terminal_status is not None or self.error_code is None:
                raise ValueError("FAILED run requires normalized error only")
        return self


class AgentRun(AgentRunSummary):
    """Complete auditable run record returned by the detail API."""

    input_message: str = Field(min_length=1, max_length=8_000)
    source_context: SafeSourceContext
    understanding: UnderstandingState | None = None
    decision: DecisionState | None = None
    final_reply: str | None = None
    handoff: HandoffState | None = None
    runtime_metadata: RuntimeMetadata
    steps: list[RunStep] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_ordered_children(self) -> Self:
        expected_steps = list(range(len(self.steps)))
        if [step.sequence for step in self.steps] != expected_steps:
            raise ValueError("run steps must have contiguous zero-based ordering")
        evidence_ids = [item.evidence_id for item in self.evidence]
        if any(evidence_id is None for evidence_id in evidence_ids):
            raise ValueError("persisted evidence requires stable evidence IDs")
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("persisted evidence IDs must be unique")
        if self.lifecycle_status is not RunLifecycleStatus.SUCCEEDED:
            if any(
                value is not None
                for value in (
                    self.understanding,
                    self.decision,
                    self.final_reply,
                    self.handoff,
                )
            ) or self.evidence:
                raise ValueError(
                    "non-successful runs cannot contain successful projections"
                )
        else:
            if self.understanding is None or self.decision is None:
                raise ValueError("successful run requires understanding and decision")
            if (
                self.understanding.primary_intent is None
                or self.understanding.request_type is None
                or self.decision.action is None
                or self.decision.goal is None
                or self.decision.rationale is None
            ):
                raise ValueError("successful run projections must be terminally typed")
        return self
