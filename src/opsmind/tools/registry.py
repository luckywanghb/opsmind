"""Registry and deterministic harness for typed read-only tools."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

from pydantic import AliasChoices, Field

from opsmind.state import StateModel
from opsmind.tools.contracts import (
    ToolFieldPresentation,
    ToolMode,
    ToolRequest,
    ToolResponse,
)

TRequest = TypeVar("TRequest", bound=ToolRequest)
TResponse = TypeVar("TResponse", bound=ToolResponse)


class ToolRuntimeError(Exception):
    """Base class for deterministic tool-runtime boundary failures."""


class UnknownToolError(ToolRuntimeError):
    """The model selected a tool that is not registered for this run."""

    def __init__(self, tool_name: str) -> None:
        super().__init__(f"unknown tool: {tool_name}")
        self.tool_name = tool_name


class UnknownToolFieldError(ToolRuntimeError):
    """A grounded response plan referenced a field absent from its schema."""

    def __init__(self, tool_name: str, field_name: str) -> None:
        super().__init__(f"unknown response field for tool {tool_name}")
        self.tool_name = tool_name
        self.field_name = field_name


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
    description: str = Field(min_length=1, max_length=500)
    mode: ToolMode = ToolMode.READ_ONLY
    timeout_seconds: float = Field(default=30.0, gt=0, allow_inf_nan=False)
    retry_limit: int = Field(default=0, ge=0)
    field_presentations: dict[str, ToolFieldPresentation] = Field(
        default_factory=dict,
        validation_alias=AliasChoices(
            "field_presentations",
            "presentation_fields",
        ),
        description=(
            "Optional typed labels and formatting metadata for fields that may "
            "be selected by a grounded response plan."
        ),
    )


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
        # ``RegisteredTool`` is frozen, but ``ToolSpec`` is a validated,
        # mutable Pydantic model.  Copy the metadata at the ownership
        # boundary so a caller cannot mutate a live registry through the
        # registration object it supplied.
        self._tools[name] = RegisteredTool(
            spec=registration.spec.model_copy(deep=True),
            request_model=registration.request_model,
            response_model=registration.response_model,
            handler=registration.handler,
        )

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

    def describe_capabilities(self) -> list[dict[str, object]]:
        """Return bounded capability metadata for non-selection model calls.

        Selection receives the complete request/response schemas from
        :meth:`describe`.  Decision and terminal prompts only need to know
        which capabilities are actually available, so they receive this
        smaller projection instead of a duplicated schema payload.
        """

        return [
            {
                "name": registration.spec.name,
                "description": registration.spec.description,
                "mode": registration.spec.mode.value,
            }
            for registration in self._tools.values()
        ]

    def describe_for_review(self, tool_name: str) -> dict[str, object]:
        """Return bounded metadata and output semantics for result review."""

        registration = self.get(tool_name)
        output_schema = registration.response_model.model_json_schema()
        properties = output_schema.get("properties")
        if isinstance(properties, dict):
            # ``message`` is an adapter presentation aid and is intentionally
            # excluded from the review contract just like it is excluded from
            # the transient result payload.
            properties = dict(properties)
            properties.pop("message", None)
            output_schema["properties"] = properties
        return {
            "name": registration.spec.name,
            "description": registration.spec.description,
            "mode": registration.spec.mode.value,
            "output_schema": _bounded_schema(output_schema),
        }

    def describe_for_response(self, tool_name: str) -> dict[str, object]:
        """Return typed presentation metadata for grounded response plans.

        The response model schema remains the source of truth for field
        existence. Explicit metadata is optional; the renderer can derive a
        conservative field label/format from the schema for a custom tool.
        """

        registration = self.get(tool_name)
        schema = registration.response_model.model_json_schema()
        properties = schema.get("properties")
        property_map = properties if isinstance(properties, dict) else {}
        fields: dict[str, object] = {}
        for name, field_schema in property_map.items():
            if name == "message":
                continue
            metadata = registration.spec.field_presentations.get(name)
            if metadata is None:
                metadata = ToolFieldPresentation.from_schema_field(
                    name,
                    field_schema if isinstance(field_schema, dict) else None,
                )
            fields[name] = metadata.model_dump(mode="json")
        for name, metadata in registration.spec.field_presentations.items():
            # Do not expose metadata for fields absent from the typed response
            # schema; such metadata could otherwise create an unreferenceable
            # presentation path.
            if name in property_map:
                fields[name] = metadata.model_dump(mode="json")
        return {
            "name": registration.spec.name,
            "description": registration.spec.description,
            "mode": registration.spec.mode.value,
            "fields": fields,
        }

    def field_presentation(
        self,
        tool_name: str,
        field_name: str,
    ) -> ToolFieldPresentation:
        """Resolve one field's presentation from its registered contract."""

        registration = self.get(tool_name)
        schema = registration.response_model.model_json_schema()
        properties = schema.get("properties")
        property_map = properties if isinstance(properties, dict) else {}
        field_schema = property_map.get(field_name)
        if field_name == "message" or field_schema is None:
            raise UnknownToolFieldError(tool_name, field_name)
        metadata = registration.spec.field_presentations.get(field_name)
        if metadata is not None:
            return metadata.model_copy(deep=True)
        return ToolFieldPresentation.from_schema_field(
            field_name,
            field_schema if isinstance(field_schema, dict) else None,
        )

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
            # Pydantic permits non-finite floats unless every custom response
            # field opts out explicitly.  The state and model boundaries are
            # standard JSON contracts, so enforce finiteness here at the
            # adapter ownership boundary before review/context projection.
            _reject_non_finite_json(typed_result.model_dump(mode="json"))
        except Exception as exc:
            raise ToolExecutionError(tool_name, "MALFORMED_TOOL_RESULT") from exc
        return ToolInvocationResult(tool_name=tool_name, output=typed_result)

    def copy(self) -> ToolRegistry:
        """Create a run-local registry snapshot without mutable shared state."""

        return ToolRegistry(
            [
                RegisteredTool(
                    spec=registration.spec.model_copy(deep=True),
                    request_model=registration.request_model,
                    response_model=registration.response_model,
                    handler=registration.handler,
                )
                for registration in self._tools.values()
            ]
        )


def _reject_non_finite_json(value: object) -> None:
    """Reject adapter values that cannot be represented by standard JSON."""

    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("non-finite adapter result")
    if isinstance(value, list):
        for item in value:
            _reject_non_finite_json(item)
    elif isinstance(value, dict):
        for item in value.values():
            _reject_non_finite_json(item)


_SCHEMA_ANNOTATION_KEYS = frozenset({"description", "title", "$comment"})
_SCHEMA_ANNOTATION_LIMIT = 500


def _bounded_schema(value: object, *, key: str | None = None) -> object:
    """Bound prose annotations while preserving JSON Schema semantics.

    Schema keywords such as ``enum``, ``anyOf``, ``items``, ``type``,
    ``$ref`` and property names are semantic contract data.  They must never
    be replaced with a depth sentinel or truncated list.  Pydantic's schema
    output is JSON-compatible; only human-readable annotation strings are
    bounded here, and all structural values are retained recursively.
    """

    if isinstance(value, str):
        if key in _SCHEMA_ANNOTATION_KEYS:
            return value[:_SCHEMA_ANNOTATION_LIMIT]
        return value
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, list):
        return [_bounded_schema(item) for item in value]
    if isinstance(value, dict):
        return {
            str(item_key): _bounded_schema(item, key=str(item_key))
            for item_key, item in value.items()
        }
    # ``model_json_schema`` is required to return JSON-compatible data.  Do
    # not stringify an unexpected value into a schema position: that would
    # turn a typed contract into misleading model metadata.
    raise TypeError("tool output schema must contain JSON-compatible values")


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
    "UnknownToolFieldError",
]
