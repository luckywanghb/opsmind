"""Provider interface consumed by :class:`ModelGateway`."""

from __future__ import annotations

from typing import Protocol, TypeVar

from pydantic import BaseModel

from opsmind.models.contracts import ModelRequest, ModelResponse

T = TypeVar("T", bound=BaseModel)


class ModelProvider(Protocol):
    """Async provider adapter contract.

    Concrete adapters own all provider SDK details.  The gateway and Agent
    nodes only see these provider-neutral methods.
    """

    async def invoke(
        self,
        request: ModelRequest,
        *,
        model: str,
    ) -> ModelResponse:
        """Generate a text response for ``request``."""

    async def invoke_structured(
        self,
        request: ModelRequest,
        response_model: type[T],
        *,
        model: str,
    ) -> T:
        """Generate and validate a response against ``response_model``."""
