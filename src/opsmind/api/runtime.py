"""Thin Agent runtime and request-scoped execution tracing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeVar

from pydantic import BaseModel

from opsmind.agent import AgentTraceEvent, run_ops_agent, run_ops_agent_with_trace
from opsmind.models import (
    ModelGateway,
    ModelProvider,
    ModelRequest,
    ModelResponse,
    StructuredModelResponse,
)
from opsmind.state import OpsAgentState
from opsmind.tools import ToolRegistry, build_default_tool_registry

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True, slots=True)
class CompletedInvocation:
    """Provider-neutral identity of one successfully completed invocation."""

    request: ModelRequest


@dataclass(frozen=True, slots=True)
class AgentRunResult:
    """Canonical state and actual completed invocation records."""

    state: OpsAgentState
    invocations: tuple[CompletedInvocation, ...]
    events: tuple[AgentTraceEvent, ...] = ()


class _RecordingProvider:
    """Request-local decorator that records only completed provider calls."""

    def __init__(
        self,
        provider: ModelProvider,
        records: list[CompletedInvocation],
    ) -> None:
        self._provider = provider
        self._records = records

    async def invoke(
        self,
        request: ModelRequest,
        *,
        model: str,
    ) -> ModelResponse:
        response = await self._provider.invoke(request, model=model)
        self._records.append(
            CompletedInvocation(request=request.model_copy(deep=True))
        )
        return response

    async def invoke_structured(
        self,
        request: ModelRequest,
        response_model: type[T],
        *,
        model: str,
    ) -> StructuredModelResponse[T]:
        response = await self._provider.invoke_structured(
            request,
            response_model,
            model=model,
        )
        self._records.append(
            CompletedInvocation(request=request.model_copy(deep=True))
        )
        return response

class OpsAgentRuntime:
    """Own the injected gateway and invoke the canonical Agent entry point."""

    def __init__(
        self,
        gateway: ModelGateway,
        tool_registry: ToolRegistry | None = None,
    ) -> None:
        self._gateway = gateway
        self._tool_registry = (tool_registry or build_default_tool_registry()).copy()

    @property
    def gateway(self) -> ModelGateway:
        return self._gateway

    @property
    def tool_registry(self) -> ToolRegistry:
        """Return a detached registry snapshot for inspection/injection."""

        return self._tool_registry.copy()

    async def run(self, state: OpsAgentState) -> OpsAgentState:
        """Delegate one request to the existing kernel unchanged."""

        return await run_ops_agent(state, self._gateway, self._tool_registry)

    async def run_with_trace(self, state: OpsAgentState) -> AgentRunResult:
        """Run the kernel with request-local records of completed calls."""

        records: list[CompletedInvocation] = []
        traced_providers = {
            name: _RecordingProvider(provider, records)
            for name, provider in self._gateway.providers.items()
        }
        traced_gateway = ModelGateway(
            routes=self._gateway.routes,
            providers=traced_providers,
        )
        result, events = await run_ops_agent_with_trace(
            state,
            traced_gateway,
            self._tool_registry,
        )
        return AgentRunResult(
            state=result,
            invocations=tuple(records),
            events=events,
        )
