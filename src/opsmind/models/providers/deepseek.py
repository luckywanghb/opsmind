"""DeepSeek Responses API adapter for the provider-neutral model contract."""

from __future__ import annotations

import json
import math
import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, NoReturn, Protocol, TypeVar, cast

from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from opsmind.models.contracts import (
    ModelRequest,
    ModelResponse,
    ModelRole,
    ModelUsage,
    StructuredModelResponse,
)
from opsmind.models.errors import ModelInvocationError, ModelStructuredOutputError
from opsmind.models.settings import DeepSeekSettings

T = TypeVar("T", bound=BaseModel)

_MISSING = object()

_ROLE_MAP: Mapping[ModelRole, str] = {
    ModelRole.SYSTEM: "system",
    ModelRole.USER: "user",
    ModelRole.ASSISTANT: "assistant",
}


class _ResponseCreator(Protocol):
    def __call__(self, **kwargs: Any) -> Awaitable[object]: ...


class _MalformedDeepSeekResponse(ValueError):
    """Internal marker for a provider response that cannot be normalized."""


def _field(value: object, name: str, default: object = None) -> object:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _optional_string(value: object, *, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise _MalformedDeepSeekResponse(f"{field_name} must be a string")
    return value


def _reject_nonstandard_json_constant(value: str) -> NoReturn:
    raise _MalformedDeepSeekResponse(
        f"structured output contains non-standard JSON constant {value!r}"
    )


class DeepSeekProvider:
    """Async adapter that isolates all DeepSeek-specific behavior.

    The provider is safe to share across concurrent calls: request timing and
    response parsing use only call-local state.  Tests may inject a client with
    an async ``responses.create`` method and a deterministic monotonic clock.
    """

    provider_name = "deepseek"

    def __init__(
        self,
        settings: DeepSeekSettings,
        *,
        client: object | None = None,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._settings = settings
        actual_client = client
        if actual_client is None:
            actual_client = AsyncOpenAI(
                api_key=settings.api_key.get_secret_value(),
                base_url=settings.base_url,
                timeout=settings.timeout_seconds,
            )
        responses = getattr(actual_client, "responses", None)
        creator = getattr(responses, "create", None)
        if not callable(creator):
            raise TypeError("client must expose an async responses.create method")
        self._create_response = cast(_ResponseCreator, creator)
        self._clock = clock

    def __repr__(self) -> str:
        return (
            "DeepSeekProvider("
            f"base_url={self._settings.base_url!r}, "
            f"reasoning_effort={self._settings.reasoning_effort!r})"
        )

    @staticmethod
    def _input(request: ModelRequest) -> list[dict[str, str]]:
        payload: list[dict[str, str]] = []
        for message in request.messages:
            role = _ROLE_MAP.get(message.role)
            if role is None:
                raise ModelInvocationError(
                    f"DeepSeek Responses API does not support role {message.role!r}"
                )
            payload.append(
                {
                    "type": "message",
                    "role": role,
                    "content": message.content,
                }
            )
        return payload

    async def _request(
        self,
        request: ModelRequest,
        *,
        model: str,
        text: Mapping[str, object] | None = None,
    ) -> tuple[object, float]:
        kwargs: dict[str, object] = {
            "model": model,
            "input": self._input(request),
            "reasoning": {"effort": self._settings.reasoning_effort},
        }
        if text is not None:
            kwargs["text"] = text

        started = self._clock()
        try:
            response = await self._create_response(**kwargs)
        except Exception:
            # SDK exceptions may contain request details.  Detach the original
            # exception entirely so standard chained tracebacks and logs can
            # never expose a credential or user content from the transport.
            pass
        else:
            elapsed_ms = (self._clock() - started) * 1000.0
            if not math.isfinite(elapsed_ms) or elapsed_ms < 0:
                raise _MalformedDeepSeekResponse(
                    "monotonic clock returned an invalid elapsed time"
                )
            return response, elapsed_ms

        raise ModelInvocationError("DeepSeek model invocation failed")

    @staticmethod
    def _content(response: object) -> str:
        output_text = _field(response, "output_text")
        if output_text is not None:
            if not isinstance(output_text, str):
                raise _MalformedDeepSeekResponse("output_text must be a string")
            return output_text

        output = _field(response, "output")
        if not isinstance(output, list):
            raise _MalformedDeepSeekResponse("response output must be a list")

        parts: list[str] = []
        for item in output:
            if _field(item, "type") != "message":
                continue
            content = _field(item, "content")
            if not isinstance(content, list):
                raise _MalformedDeepSeekResponse(
                    "response message content must be a list"
                )
            for part in content:
                if _field(part, "type") != "output_text":
                    continue
                text = _field(part, "text")
                if not isinstance(text, str):
                    raise _MalformedDeepSeekResponse(
                        "response output text must be a string"
                    )
                parts.append(text)
        return "".join(parts)

    @staticmethod
    def _usage(response: object) -> ModelUsage | None:
        usage = _field(response, "usage")
        if usage is None:
            return None
        input_tokens = _field(usage, "input_tokens", _MISSING)
        output_tokens = _field(usage, "output_tokens", _MISSING)
        total_tokens = _field(usage, "total_tokens", _MISSING)
        if all(
            value is _MISSING
            for value in (input_tokens, output_tokens, total_tokens)
        ):
            raise _MalformedDeepSeekResponse(
                "usage must expose at least one token count"
            )
        return ModelUsage.model_validate(
            {
                "input_tokens": None if input_tokens is _MISSING else input_tokens,
                "output_tokens": None if output_tokens is _MISSING else output_tokens,
                "total_tokens": None if total_tokens is _MISSING else total_tokens,
            }
        )

    @classmethod
    def _metadata(
        cls,
        response: object,
        *,
        content: str,
        requested_model: str,
        latency_ms: float,
    ) -> ModelResponse:
        returned_model = _optional_string(
            _field(response, "model"), field_name="model"
        )
        if returned_model is not None and returned_model != requested_model:
            raise _MalformedDeepSeekResponse(
                "provider response model does not match the requested model"
            )

        status = _optional_string(
            _field(response, "status"), field_name="status"
        )
        if status is None:
            status = _optional_string(
                _field(response, "finish_reason"), field_name="finish reason"
            )
        request_id = _optional_string(
            _field(response, "_request_id"), field_name="request ID"
        )

        return ModelResponse(
            content=content,
            provider=cls.provider_name,
            model=returned_model or requested_model,
            finish_reason=status,
            usage=cls._usage(response),
            latency_ms=latency_ms,
            request_id=request_id,
        )

    async def invoke(
        self,
        request: ModelRequest,
        *,
        model: str,
    ) -> ModelResponse:
        """Invoke DeepSeek for plain text and normalize provider metadata."""

        try:
            response, latency_ms = await self._request(request, model=model)
            content = self._content(response)
            if not content.strip():
                raise _MalformedDeepSeekResponse("provider returned empty text output")
            return self._metadata(
                response,
                content=content,
                requested_model=model,
                latency_ms=latency_ms,
            )
        except ModelInvocationError:
            raise
        except Exception:
            raise ModelInvocationError("DeepSeek model invocation failed") from None

    async def invoke_structured(
        self,
        request: ModelRequest,
        response_model: type[T],
        *,
        model: str,
    ) -> StructuredModelResponse[T]:
        """Request JSON Schema output, parse JSON, then validate with Pydantic."""

        if not isinstance(response_model, type) or not issubclass(
            response_model, BaseModel
        ):
            raise ModelStructuredOutputError(
                "response_model must be a Pydantic BaseModel subclass"
            )

        try:
            schema = response_model.model_json_schema()
        except Exception as exc:
            raise ModelStructuredOutputError(
                f"could not generate JSON Schema for {response_model.__name__}"
            ) from exc

        text_config: dict[str, object] = {
            "format": {
                "type": "json_schema",
                "name": response_model.__name__,
                "schema": schema,
            }
        }
        try:
            response, latency_ms = await self._request(
                request,
                model=model,
                text=text_config,
            )
        except ModelInvocationError:
            raise
        except _MalformedDeepSeekResponse:
            raise ModelInvocationError("DeepSeek model invocation failed") from None
        except Exception:
            raise ModelInvocationError("DeepSeek model invocation failed") from None

        try:
            content = self._content(response)
            if not content.strip():
                raise _MalformedDeepSeekResponse(
                    "provider returned empty structured output"
                )
            payload = json.loads(
                content,
                parse_constant=_reject_nonstandard_json_constant,
            )
            parsed = response_model.model_validate(payload)
            metadata = self._metadata(
                response,
                content=content,
                requested_model=model,
                latency_ms=latency_ms,
            )
        except (
            json.JSONDecodeError,
            ValidationError,
            _MalformedDeepSeekResponse,
        ) as exc:
            raise ModelStructuredOutputError(
                f"DeepSeek structured output does not match {response_model.__name__}"
            ) from exc

        return StructuredModelResponse[T](parsed=parsed, response=metadata)
