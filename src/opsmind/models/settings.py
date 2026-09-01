"""Secret-safe configuration for the DeepSeek model provider."""

from __future__ import annotations

import math
import os
from collections.abc import Mapping
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_CHEAP_MODEL = "deepseek-v4-flash"
DEFAULT_STRONG_MODEL = "deepseek-v4-pro"
DEFAULT_TIMEOUT_SECONDS = 60.0

ReasoningEffort = Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"]


class DeepSeekSettings(BaseModel):
    """Validated provider configuration loaded explicitly by the runtime.

    ``SecretStr`` keeps the API key redacted from repr, logs, JSON, and normal
    model dumps.  The clear value is read only when constructing the SDK
    client.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    api_key: SecretStr
    base_url: str = DEFAULT_DEEPSEEK_BASE_URL
    cheap_model: str = DEFAULT_CHEAP_MODEL
    strong_model: str = DEFAULT_STRONG_MODEL
    timeout_seconds: float = Field(default=DEFAULT_TIMEOUT_SECONDS, gt=0)
    reasoning_effort: ReasoningEffort = "none"

    @field_validator("api_key")
    @classmethod
    def reject_blank_api_key(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("DeepSeek API key must not be blank")
        return value

    @field_validator("base_url", "cheap_model", "strong_model")
    @classmethod
    def strip_non_blank_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("configuration value must not be blank")
        return stripped

    @field_validator("timeout_seconds")
    @classmethod
    def require_finite_timeout(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("timeout must be finite")
        return value

    @field_validator("timeout_seconds", mode="before")
    @classmethod
    def reject_boolean_timeout(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("timeout must be a number")
        return value

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Self:
        """Load supported environment variables without mutating global state."""

        values = os.environ if environ is None else environ
        payload: dict[str, object] = {
            "api_key": values.get("DEEPSEEK_API_KEY"),
            "base_url": values.get("DEEPSEEK_BASE_URL", DEFAULT_DEEPSEEK_BASE_URL),
            "cheap_model": values.get("OPSMIND_CHEAP_MODEL", DEFAULT_CHEAP_MODEL),
            "strong_model": values.get("OPSMIND_STRONG_MODEL", DEFAULT_STRONG_MODEL),
        }
        if "DEEPSEEK_TIMEOUT_SECONDS" in values:
            payload["timeout_seconds"] = values["DEEPSEEK_TIMEOUT_SECONDS"]
        if "DEEPSEEK_REASONING_EFFORT" in values:
            payload["reasoning_effort"] = values["DEEPSEEK_REASONING_EFFORT"]
        return cls.model_validate(payload)
