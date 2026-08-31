"""Error hierarchy for model routing, provider invocation, and parsing."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from opsmind.models.contracts import ModelProfile


class ModelGatewayError(Exception):
    """Base exception for failures at the model gateway boundary."""


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
