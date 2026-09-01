"""Explicit environment configuration for the HTTP runtime."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict

ModelProviderName = Literal["mock", "deepseek"]


class RuntimeSettings(BaseModel):
    """Small, secret-free selector for runtime provider composition."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model_provider: ModelProviderName = "mock"

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Self:
        values = os.environ if environ is None else environ
        return cls.model_validate(
            {"model_provider": values.get("OPSMIND_MODEL_PROVIDER", "mock")}
        )
