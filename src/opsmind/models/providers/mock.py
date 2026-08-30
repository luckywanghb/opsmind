"""Deterministic async provider for gateway and future Agent-node tests."""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import TypeVar, cast

from pydantic import BaseModel

from opsmind.models.contracts import (
    ModelMessage,
    ModelProfile,
    ModelRequest,
    ModelResponse,
    ModelTask,
    StructuredModelResponse,
)
from opsmind.models.errors import ModelInvocationError

T = TypeVar("T", bound=BaseModel)


class MockResponseQueueExhaustedError(ModelInvocationError):
    """Raised when a mock invocation has no predefined response left."""

    def __init__(self, *, structured: bool) -> None:
        kind = "structured" if structured else "text"
        super().__init__(f"mock {kind} response queue is exhausted")


@dataclass(frozen=True, slots=True)
class MockInvocation:
    """Immutable record of one request received by the mock provider."""

    request: ModelRequest
    model: str

    @property
    def profile(self) -> ModelProfile:
        """The logical profile selected for this invocation."""

        return self.request.profile

    @property
    def task(self) -> ModelTask:
        """The purpose declared for this invocation."""

        return self.request.task

    @property
    def messages(self) -> list[ModelMessage]:
        """The messages supplied for this invocation."""

        return self.request.messages


class MockModelProvider:
    """Queue-backed provider with inspectable invocation history.

    ``responses`` supplies text responses.  ``structured_responses`` supplies
    payloads for structured calls; when it is omitted, structured calls use
    the same response queue.  Queue items may be model instances, mappings,
    text/JSON strings, ``ModelResponse`` instances, or exceptions to raise.
    """

    def __init__(
        self,
        responses: Iterable[object] | None = None,
        *,
        structured_responses: Iterable[object] | None = None,
        provider_name: str = "mock",
    ) -> None:
        if not isinstance(provider_name, str) or not provider_name.strip():
            raise ValueError("provider_name must not be blank")
        self.provider_name = provider_name
        self._responses: deque[object] = deque(
            responses if responses is not None else ()
        )
        self._structured_responses: deque[object] | None = (
            deque(structured_responses)
            if structured_responses is not None
            else None
        )
        self._history: list[MockInvocation] = []

    def _history_snapshot(self) -> list[MockInvocation]:
        """Return detached records so callers cannot mutate provider state."""

        return [
            MockInvocation(
                request=invocation.request.model_copy(deep=True),
                model=invocation.model,
            )
            for invocation in self._history
        ]

    @property
    def invocations(self) -> list[MockInvocation]:
        """Alias for the invocation history used by tests."""

        return self._history_snapshot()

    @property
    def history(self) -> list[MockInvocation]:
        """A detached snapshot of all recorded invocations."""

        return self._history_snapshot()

    @property
    def calls(self) -> list[MockInvocation]:
        """Alias for the invocation history used by tests."""

        return self._history_snapshot()

    @property
    def invocation_count(self) -> int:
        return len(self._history)

    @property
    def call_count(self) -> int:
        return len(self._history)

    @property
    def remaining_responses(self) -> int:
        """Number of remaining text responses in the default queue."""

        return len(self._responses)

    @property
    def remaining_structured_responses(self) -> int | None:
        """Number of remaining dedicated structured responses, if configured."""

        if self._structured_responses is None:
            return None
        return len(self._structured_responses)

    def enqueue_response(self, response: object) -> None:
        """Append one response to the text/default queue."""

        self._responses.append(response)

    def enqueue(self, response: object) -> None:
        """Append one response to the text/default queue.

        This short alias keeps the queue API convenient for Agent-node tests.
        """

        self.enqueue_response(response)

    def enqueue_structured_response(self, response: object) -> None:
        """Append one response to the dedicated structured queue."""

        if self._structured_responses is None:
            self._structured_responses = deque()
        self._structured_responses.append(response)

    def enqueue_structured(self, response: object) -> None:
        """Append one response to the dedicated structured queue."""

        self.enqueue_structured_response(response)

    def _record(self, request: ModelRequest, model: str) -> None:
        self._history.append(
            MockInvocation(request=request.model_copy(deep=True), model=model)
        )

    @staticmethod
    def _raise_if_exception(response: object) -> None:
        if isinstance(response, BaseException):
            raise response

    def _next_response(self, *, structured: bool) -> object:
        queue = self._structured_responses if structured else self._responses
        if queue is None:
            queue = self._responses
        if not queue:
            raise MockResponseQueueExhaustedError(structured=structured)
        return queue.popleft()

    def _as_text_response(self, response: object, *, model: str) -> ModelResponse:
        self._raise_if_exception(response)
        if isinstance(response, ModelResponse):
            return ModelResponse.model_validate(response)
        if isinstance(response, str):
            return ModelResponse(
                content=response,
                provider=self.provider_name,
                model=model,
            )
        if isinstance(response, Mapping):
            payload = dict(response)
            payload.setdefault("provider", self.provider_name)
            payload.setdefault("model", model)
            return ModelResponse.model_validate(payload)
        raise TypeError(
            "mock text response must be a ModelResponse, mapping, string, "
            "or exception"
        )

    async def invoke(
        self,
        request: ModelRequest,
        *,
        model: str,
    ) -> ModelResponse:
        """Return the next predefined text response."""

        self._record(request, model)
        response = self._next_response(structured=False)
        return self._as_text_response(response, model=model)

    async def invoke_structured(
        self,
        request: ModelRequest,
        response_model: type[T],
        *,
        model: str,
    ) -> StructuredModelResponse[T]:
        """Validate the next predefined payload and preserve its metadata."""

        self._record(request, model)
        response = self._next_response(structured=True)
        self._raise_if_exception(response)

        metadata = ModelResponse(
            content="",
            provider=self.provider_name,
            model=model,
        )
        payload: object = response
        if isinstance(response, StructuredModelResponse):
            metadata = ModelResponse.model_validate(response.response)
            payload = response.parsed
        elif isinstance(response, Mapping) and {
            "parsed",
            "response",
        }.issubset(response):
            metadata = ModelResponse.model_validate(response["response"])
            payload = response["parsed"]
        elif isinstance(response, ModelResponse):
            metadata = ModelResponse.model_validate(response)
            try:
                payload = json.loads(response.content)
            except json.JSONDecodeError:
                payload = response.content
        elif isinstance(response, str):
            try:
                payload = json.loads(response)
            except json.JSONDecodeError:
                payload = response

        parsed = response_model.model_validate(payload)
        return cast(
            StructuredModelResponse[T],
            StructuredModelResponse(
                parsed=parsed,
                response=metadata,
            )
        )
