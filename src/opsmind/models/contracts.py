"""Provider-neutral contracts used by the OpsMind model gateway.

The models in this module intentionally describe only the boundary between an
Agent node and a model provider.  They do not contain prompts, business
decisions, or provider-specific request fields.
"""

from __future__ import annotations

import math
from enum import StrEnum
from typing import Annotated, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator


class ModelProfile(StrEnum):
    """Logical model quality/cost profile selected by an Agent node."""

    CHEAP = "CHEAP"
    STRONG = "STRONG"
    FALLBACK = "FALLBACK"


class ModelTask(StrEnum):
    """Purpose of a model invocation for tracing and evaluation."""

    REQUEST_UNDERSTANDING = "REQUEST_UNDERSTANDING"
    ACTION_DECISION = "ACTION_DECISION"
    TOOL_SELECTION = "TOOL_SELECTION"
    TOOL_RESULT_REVIEW = "TOOL_RESULT_REVIEW"
    CLARIFICATION = "CLARIFICATION"
    RESPONSE_GENERATION = "RESPONSE_GENERATION"
    HANDOFF_GENERATION = "HANDOFF_GENERATION"
    # Grounded response planning uses the existing response-generation task
    # identity so provider/API consumers that know the Phase-1 task set remain
    # compatible while callers can name the new typed boundary explicitly.
    GROUNDED_RESPONSE_PLAN = "RESPONSE_GENERATION"


class ModelRole(StrEnum):
    """Provider-neutral role for one message in a model request."""

    SYSTEM = "SYSTEM"
    USER = "USER"
    ASSISTANT = "ASSISTANT"
    TOOL = "TOOL"


class ModelContract(BaseModel):
    """Base configuration shared by all public model contracts."""

    model_config = ConfigDict(
        extra="forbid",
        revalidate_instances="always",
        validate_assignment=True,
    )


class ModelMessage(ModelContract):
    """One provider-neutral message supplied to a model."""

    role: ModelRole
    content: str


def _reject_non_finite_json(value: JsonValue, path: str = "$") -> None:
    """Reject numbers that cannot be represented by standard JSON."""

    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"non-finite number at {path}")
    if isinstance(value, list):
        for index, item in enumerate(value):
            _reject_non_finite_json(item, f"{path}[{index}]")
    elif isinstance(value, dict):
        for key, item in value.items():
            _reject_non_finite_json(item, f"{path}.{key}")


def _validate_metadata(
    value: dict[str, JsonValue],
) -> dict[str, JsonValue]:
    _reject_non_finite_json(value)
    return value


def _validate_non_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("value must not be blank")
    return value


class ModelRequest(ModelContract):
    """Input to a model provider, independent of provider SDK schemas."""

    task: ModelTask
    profile: ModelProfile
    messages: list[ModelMessage] = Field(min_length=1)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    _validate_metadata = field_validator("metadata")(_validate_metadata)


class ModelRoute(ModelContract):
    """Explicit mapping from a logical profile to a provider/model pair."""

    profile: ModelProfile
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)

    _validate_provider = field_validator("provider", "model")(_validate_non_blank)


NonNegativeToken = Annotated[int, Field(ge=0, strict=True)]
FiniteNonNegativeFloat = Annotated[
    float,
    Field(ge=0, strict=True, allow_inf_nan=False),
]


class ModelUsage(ModelContract):
    """Optional token accounting returned by a provider."""

    input_tokens: NonNegativeToken | None = None
    output_tokens: NonNegativeToken | None = None
    total_tokens: NonNegativeToken | None = None


class ModelResponse(ModelContract):
    """Unified text response and observability metadata from a provider."""

    content: str
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    finish_reason: str | None = None
    usage: ModelUsage | None = None
    latency_ms: FiniteNonNegativeFloat | None = None
    request_id: str | None = None

    _validate_provider = field_validator("provider", "model")(_validate_non_blank)


StructuredT = TypeVar("StructuredT", bound=BaseModel)


class StructuredModelResponse(ModelContract, Generic[StructuredT]):
    """Validated structured output together with its provider response.

    Structured model calls still expose the caller's validated Pydantic model
    through ``parsed`` while retaining the response metadata needed for
    tracing and cost evaluation.  The wrapper deliberately contains no
    provider-specific fields.
    """

    parsed: StructuredT
    response: ModelResponse
