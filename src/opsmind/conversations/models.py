"""Typed conversation persistence and restoration contracts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Self

from pydantic import ConfigDict, Field, field_validator, model_validator

from opsmind.state import ResolutionStatus, StateModel

MAX_CONVERSATION_ID_LENGTH = 128
MAX_CONVERSATION_CONTENT_LENGTH = 8_000
MAX_CHECKPOINT_TEXT_LENGTH = 2_000
MAX_CHECKPOINT_ITEMS = 20
MAX_IMPORTANT_ENTITIES = 20


class ConversationStatus(StrEnum):
    ACTIVE = "ACTIVE"
    WAITING_USER = "WAITING_USER"
    RESOLVED = "RESOLVED"
    TRANSFERRED = "TRANSFERRED"
    CLOSED = "CLOSED"


class ConversationRole(StrEnum):
    USER = "USER"
    ASSISTANT = "ASSISTANT"


class ConversationModel(StateModel):
    """Immutable validated value at the persistence boundary."""

    model_config = ConfigDict(
        extra="forbid",
        revalidate_instances="always",
        validate_assignment=True,
        frozen=True,
    )


class ConversationThread(ConversationModel):
    thread_id: str = Field(min_length=1, max_length=MAX_CONVERSATION_ID_LENGTH)
    created_at: datetime
    updated_at: datetime
    status: ConversationStatus
    original_query: str = Field(
        min_length=1, max_length=MAX_CONVERSATION_CONTENT_LENGTH
    )
    previous_resolution_status: ResolutionStatus
    latest_run_id: str = Field(min_length=1, max_length=MAX_CONVERSATION_ID_LENGTH)
    turn_count: int = Field(ge=0, strict=True)
    revision: int = Field(ge=0, strict=True)
    user_id: str | None = Field(default=None, max_length=512)
    active_run_id: str | None = Field(
        default=None, max_length=MAX_CONVERSATION_ID_LENGTH
    )

    @model_validator(mode="after")
    def validate_timestamps(self) -> Self:
        if self.created_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise ValueError("conversation timestamps must be timezone-aware")
        if self.updated_at < self.created_at:
            raise ValueError("conversation update precedes creation")
        return self


class ConversationTurn(ConversationModel):
    turn_id: str = Field(min_length=1, max_length=MAX_CONVERSATION_ID_LENGTH)
    thread_id: str = Field(min_length=1, max_length=MAX_CONVERSATION_ID_LENGTH)
    sequence: int = Field(ge=1, strict=True)
    role: ConversationRole
    content: str = Field(min_length=1, max_length=MAX_CONVERSATION_CONTENT_LENGTH)
    request_id: str = Field(min_length=1, max_length=MAX_CONVERSATION_ID_LENGTH)
    run_id: str = Field(min_length=1, max_length=MAX_CONVERSATION_ID_LENGTH)
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("turn timestamp must be timezone-aware")
        return value


class ConversationCheckpoint(ConversationModel):
    """Safe cross-run projection; deliberately not a previous Agent state."""

    thread_id: str = Field(min_length=1, max_length=MAX_CONVERSATION_ID_LENGTH)
    revision: int = Field(ge=1, strict=True)
    original_query: str = Field(
        min_length=1, max_length=MAX_CONVERSATION_CONTENT_LENGTH
    )
    previous_resolution_status: ResolutionStatus
    task_objective: str | None = Field(
        default=None, max_length=MAX_CHECKPOINT_TEXT_LENGTH
    )
    task_constraints: list[str] = Field(
        default_factory=list, max_length=MAX_CHECKPOINT_ITEMS
    )
    confirmed_facts: list[str] = Field(
        default_factory=list, max_length=MAX_CHECKPOINT_ITEMS
    )
    unresolved_questions: list[str] = Field(
        default_factory=list, max_length=MAX_CHECKPOINT_ITEMS
    )
    latest_understanding_summary: str | None = Field(
        default=None, max_length=MAX_CHECKPOINT_TEXT_LENGTH
    )
    important_entities: dict[str, str | int | bool] = Field(default_factory=dict)
    last_assistant_message: str | None = Field(
        default=None, max_length=MAX_CHECKPOINT_TEXT_LENGTH
    )
    latest_run_id: str = Field(min_length=1, max_length=MAX_CONVERSATION_ID_LENGTH)
    updated_at: datetime

    @field_validator(
        "task_constraints", "confirmed_facts", "unresolved_questions"
    )
    @classmethod
    def validate_bounded_text_list(cls, value: list[str]) -> list[str]:
        if any(
            not item.strip() or len(item) > MAX_CHECKPOINT_TEXT_LENGTH
            for item in value
        ):
            raise ValueError("checkpoint text list contains an invalid item")
        return value

    @field_validator("important_entities")
    @classmethod
    def validate_entities(
        cls, value: dict[str, str | int | bool]
    ) -> dict[str, str | int | bool]:
        if len(value) > MAX_IMPORTANT_ENTITIES:
            raise ValueError("checkpoint contains too many important entities")
        for key, item in value.items():
            if not key or len(key) > 256:
                raise ValueError("checkpoint entity key is invalid")
            if isinstance(item, str) and (not item.strip() or len(item) > 512):
                raise ValueError("checkpoint entity value is invalid")
        return value

    @field_validator("updated_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("checkpoint timestamp must be timezone-aware")
        return value


class ConversationContextSnapshot(ConversationModel):
    thread: ConversationThread
    checkpoint: ConversationCheckpoint | None = None
    recent_turns: list[ConversationTurn] = Field(default_factory=list, max_length=6)

    @model_validator(mode="after")
    def validate_thread_relations(self) -> Self:
        if self.checkpoint and self.checkpoint.thread_id != self.thread.thread_id:
            raise ValueError("checkpoint belongs to another thread")
        if any(turn.thread_id != self.thread.thread_id for turn in self.recent_turns):
            raise ValueError("recent turn belongs to another thread")
        sequences = [turn.sequence for turn in self.recent_turns]
        if sequences != sorted(sequences) or len(sequences) != len(set(sequences)):
            raise ValueError("recent turns must be uniquely ordered")
        return self


class ConversationLease(ConversationModel):
    """Optimistic ownership token for one in-flight run in a thread."""

    thread_id: str
    request_id: str
    run_id: str
    revision: int = Field(ge=1, strict=True)
    user_turn_sequence: int = Field(ge=1, strict=True)
    context: ConversationContextSnapshot


class ConversationThreadDetail(ConversationModel):
    thread: ConversationThread
    turns: list[ConversationTurn] = Field(default_factory=list)
    checkpoint: ConversationCheckpoint | None = None

    @model_validator(mode="after")
    def validate_detail(self) -> Self:
        if len(self.turns) != self.thread.turn_count:
            raise ValueError("thread turn count does not match stored turns")
        if [turn.sequence for turn in self.turns] != list(
            range(1, len(self.turns) + 1)
        ):
            raise ValueError("thread turns are not contiguous")
        return self
