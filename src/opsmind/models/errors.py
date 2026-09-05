"""Error hierarchy for model routing, provider invocation, and parsing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from opsmind.models.contracts import ModelProfile


StructuredFailureCategory = Literal[
    "invocation_failed",
    "empty_output",
    "json_decode",
    "schema_mismatch",
    "response_metadata",
]


@dataclass(frozen=True, slots=True)
class StructuredNodeFailureDiagnostic:
    """Allowlisted internal metadata for one failed structured node.

    This object is intentionally limited to stable execution identity. It
    carries no model text, prompts, payloads, validation values, credentials,
    or exception objects. Request correlation is supplied by the API's
    request ID when the diagnostic is emitted.
    """

    node: str
    expected_schema_name: str
    logical_profile: str
    category: StructuredFailureCategory


class ModelGatewayError(Exception):
    """Base exception for failures at the model gateway boundary."""

    diagnostic: StructuredNodeFailureDiagnostic | None

    def __init__(self, *args: object) -> None:
        super().__init__(*args)
        self.diagnostic = None


class ModelRouteConfigurationError(ModelGatewayError):
    """Raised when an explicitly configured route is malformed."""


class ModelRouteNotFoundError(ModelGatewayError):
    """Raised when a request profile has no configured route."""

    def __init__(self, profile: ModelProfile | str) -> None:
        self.profile = profile
        super().__init__(f"no model route configured for profile {profile!r}")


class ModelProviderNotFoundError(ModelGatewayError):
    """Raised when a route references an unregistered provider."""

    def __init__(self, provider: str, profile: ModelProfile | str) -> None:
        self.provider = provider
        self.profile = profile
        super().__init__(
            f"provider {provider!r} for profile {profile!r} is not registered"
        )


class ModelProviderAlreadyRegisteredError(ModelGatewayError):
    """Raised when a provider name would overwrite an existing registration."""

    def __init__(self, provider: str) -> None:
        self.provider = provider
        super().__init__(f"provider {provider!r} is already registered")


class ModelInvocationError(ModelGatewayError):
    """Raised when a provider fails or returns an invalid text response."""


class ModelStructuredOutputError(ModelGatewayError):
    """Raised when structured output cannot be validated against its schema."""
