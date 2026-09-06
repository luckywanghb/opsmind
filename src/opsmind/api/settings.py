"""Explicit environment configuration for the HTTP runtime."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator

ModelProviderName = Literal["mock", "deepseek"]


class RuntimeSettings(BaseModel):
    """Small, secret-free selector for runtime provider composition."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model_provider: ModelProviderName = "mock"
    run_store_path: Path = Path(".opsmind/opsmind.db")
    build_sha: str | None = Field(default=None, min_length=1, max_length=256)

    @field_validator("run_store_path", mode="before")
    @classmethod
    def reject_empty_store_path(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            raise ValueError("run_store_path must not be blank")
        return value

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Self:
        values = os.environ if environ is None else environ
        build_sha = values.get("OPSMIND_BUILD_SHA")
        return cls.model_validate(
            {
                "model_provider": values.get("OPSMIND_MODEL_PROVIDER", "mock"),
                "run_store_path": values.get(
                    "OPSMIND_RUN_STORE_PATH", ".opsmind/opsmind.db"
                ),
                "build_sha": build_sha if build_sha else None,
            }
        )
