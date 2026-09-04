"""Registry and deterministic harness for typed read-only tools."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

from pydantic import Field

from opsmind.state import StateModel
from opsmind.tools.contracts import ToolMode, ToolRequest, ToolResponse

TRequest = TypeVar("TRequest", bound=ToolRequest)
TResponse = TypeVar("TResponse", bound=ToolResponse)


class ToolRuntimeError(Exception):
    """Base class for deterministic tool-runtime boundary failures."""


class UnknownToolError(ToolRuntimeError):
    """The model selected a tool that is not registered for this run."""

    def __init__(self, tool_name: str) -> None:
        super().__init__(f"unknown tool: {tool_name}")
        self.tool_name = tool_name


class ToolArgumentsError(ToolRuntimeError):
    """Tool arguments failed the registered Pydantic request schema."""

    def __init__(self, tool_name: str, message: str) -> None:
        super().__init__(f"invalid arguments for tool {tool_name}: {message}")
        self.tool_name = tool_name


class ToolPolicyError(ToolRuntimeError):
    """The selected tool violates the active capability boundary."""

    def __init__(self, tool_name: str, mode: ToolMode) -> None:
        super().__init__(
            f"tool {tool_name} with mode {mode.value} is blocked by READ_ONLY policy"
        )
        self.tool_name = tool_name
        self.mode = mode


class ToolExecutionError(ToolRuntimeError):
    """A registered adapter failed or exceeded its runtime boundary."""

    def __init__(self, tool_name: str, code: str = "TOOL_EXECUTION_FAILED") -> None:
        # Never include adapter exception text: adapters may accidentally carry
        # provider payloads or user data in their exception messages.
        super().__init__(f"tool {tool_name} execution failed")
        self.tool_name = tool_name
        self.code = code


class ToolSpec(StateModel):
    """Public, model-visible metadata for one registered tool."""

    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    mode: ToolMode = ToolMode.READ_ONLY
    timeout_seconds: float = Field(default=30.0, gt=0, allow_inf_nan=False)
    retry_limit: int = Field(default=0, ge=0)


ToolHandler = Callable[..., Awaitable[ToolResponse]]


@dataclass(frozen=True, slots=True)
class RegisteredTool:
    """An immutable registration joining metadata, schemas and an adapter."""

    spec: ToolSpec
    request_model: type[ToolRequest]
    response_model: type[ToolResponse]
    handler: ToolHandler

    def model_description(self) -> dict[str, object]:
        """Return only JSON-schema metadata safe to place in a model prompt."""

        return {
            "name": self.spec.name,
            "description": self.spec.description,
            "mode": self.spec.mode.value,
            "input_schema": self.request_model.model_json_schema(),
            "output_schema": self.response_model.model_json_schema(),
        }


class ToolCall(StateModel):
    """Validated selected tool and typed request used by the harness."""

    tool_name: str = Field(min_length=1)
    arguments: dict[str, object]


@dataclass(frozen=True, slots=True)
class ToolInvocationResult:
    """Transient result retained only between execute and review nodes."""

    tool_name: str
    output: ToolResponse | None
    error_code: str | None = None

    @property
    def status(self) -> str:
        if self.error_code:
            return "failed"
        assert self.output is not None
        return self.output.result_status.value


class ToolRegistry:
    """Per-runtime registry that validates, authorizes and executes tools.

    A registry is intentionally ordinary state owned by an ``OpsAgentRuntime``
    and copied for each graph run.  No module-level mutable registry exists,
    which keeps concurrent runs and tests isolated.
    """

    def __init__(self, tools: list[RegisteredTool] | None = None) -> None:
        self._tools: dict[str, RegisteredTool] = {}
        for registration in tools or []:
            self.register(registration)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._tools)

    @property
    def specs(self) -> tuple[ToolSpec, ...]:
        return tuple(
            registration.spec.model_copy(deep=True)
            for registration in self._tools.values()
        )

    def register(self, registration: RegisteredTool) -> None:
        """Register one tool and reject accidental name collisions."""

        name = registration.spec.name
        if name in self._tools:
            raise ValueError(f"tool {name!r} is already registered")
        if not issubclass(registration.request_model, ToolRequest):
            raise TypeError("request_model must extend ToolRequest")
        if not issubclass(registration.response_model, ToolResponse):
            raise TypeError("response_model must extend ToolResponse")
        self._tools[name] = registration

    def get(self, tool_name: str) -> RegisteredTool:
        registration = self._tools.get(tool_name)
        if registration is None:
            raise UnknownToolError(tool_name)
        return registration

    def describe(self) -> list[dict[str, object]]:
        """Return detached model-visible descriptions in registration order."""

        return [
            registration.model_description()
            for registration in self._tools.values()
        ]

    def validate_call(self, tool_name: str, arguments: object) -> ToolCall:
        """Validate a model selection without executing an adapter."""

        if not isinstance(tool_name, str) or not tool_name.strip():
            raise UnknownToolError(str(tool_name))
        registration = self.get(tool_name)
        if not isinstance(arguments, dict):
            raise ToolArgumentsError(tool_name, "arguments must be an object")
        try:
            typed = registration.request_model.model_validate(arguments)
        except Exception as exc:
            # The schema failure itself is useful to tests and observability,
            # but not to end users; graph/API boundaries redact it later.
            raise ToolArgumentsError(tool_name, "schema validation failed") from exc
        return ToolCall(
            tool_name=tool_name,
            arguments=typed.model_dump(mode="json"),
        )

    async def execute(
        self,
        tool_name: str,
        arguments: object,
        *,
        timeout_seconds: float | None = None,
    ) -> ToolInvocationResult:
        """Validate, enforce READ_ONLY, timeout and normalize one call."""

        registration = self.get(tool_name)
        if registration.spec.mode is not ToolMode.READ_ONLY:
            raise ToolPolicyError(tool_name, registration.spec.mode)
        call = self.validate_call(tool_name, arguments)
        typed_request = registration.request_model.model_validate(call.arguments)
        timeout = registration.spec.timeout_seconds
        if timeout_seconds is not None:
            timeout = min(timeout, timeout_seconds)
        try:
            result = await asyncio.wait_for(
                registration.handler(typed_request),
                timeout=timeout,
            )
        except TimeoutError as exc:
            raise ToolExecutionError(tool_name, "TOOL_TIMEOUT") from exc
        except ToolRuntimeError:
            raise
        except Exception as exc:
            raise ToolExecutionError(tool_name) from exc
        try:
            typed_result = registration.response_model.model_validate(result)
        except Exception as exc:
            raise ToolExecutionError(tool_name, "MALFORMED_TOOL_RESULT") from exc
        return ToolInvocationResult(tool_name=tool_name, output=typed_result)

    def copy(self) -> ToolRegistry:
        """Create a run-local registry snapshot without mutable shared state."""

        return ToolRegistry(list(self._tools.values()))


__all__ = [
    "RegisteredTool",
    "ToolArgumentsError",
    "ToolCall",
    "ToolExecutionError",
    "ToolInvocationResult",
    "ToolMode",
    "ToolPolicyError",
    "ToolRegistry",
    "ToolRuntimeError",
    "ToolSpec",
    "UnknownToolError",
]
