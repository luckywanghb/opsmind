"""Additional independent tests for model-gateway contract edges.

These tests deliberately use a tiny provider double for the structured
response boundary.  The queue-backed mock is covered elsewhere; testing the
gateway with a provider that returns the public wrapper directly ensures the
gateway, rather than only the mock adapter, validates both halves of it.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Coroutine
from enum import StrEnum
from typing import Any, TypeVar

import pytest
from pydantic import BaseModel, ValidationError

from opsmind.models import (
    MockModelProvider,
    ModelGateway,
    ModelInvocationError,
    ModelMessage,
    ModelProfile,
    ModelRequest,
    ModelResponse,
    ModelRole,
    ModelRoute,
    ModelRouteConfigurationError,
    ModelStructuredOutputError,
    ModelTask,
    ModelUsage,
    StructuredModelResponse,
)

T = TypeVar("T")


def run_async(operation: Coroutine[Any, Any, T]) -> T:
    """Run one async operation without requiring a pytest async plugin."""

    return asyncio.run(operation)


def make_request(
    profile: ModelProfile = ModelProfile.CHEAP,
    *,
    metadata: dict[str, object] | None = None,
) -> ModelRequest:
    return ModelRequest(
        task=ModelTask.REQUEST_UNDERSTANDING,
        profile=profile,
        messages=[ModelMessage(role=ModelRole.USER, content="hello")],
        metadata=metadata if metadata is not None else {"case": "edge"},
    )


def make_gateway(
    provider: object,
    *,
    provider_name: str = "adapter",
    profile: ModelProfile = ModelProfile.CHEAP,
    model: str | None = None,
) -> ModelGateway:
    route = ModelRoute(
        profile=profile,
        provider=provider_name,
        model=model or f"{provider_name}-{profile.name.lower()}",
    )
    return ModelGateway(routes={profile: route}, providers={provider_name: provider})  # type: ignore[arg-type]


class StructuredAnswer(BaseModel):
    answer: str


class DirectStructuredProvider:
    """Provider double that returns a pre-built structured envelope."""

    def __init__(self, result: object) -> None:
        self.result = result

    async def invoke(
        self,
        request: ModelRequest,
        *,
        model: str,
    ) -> ModelResponse:
        return ModelResponse(content="unused", provider="adapter", model=model)

    async def invoke_structured(
        self,
        request: ModelRequest,
        response_model: type[BaseModel],
        *,
        model: str,
    ) -> object:
        return self.result


class RaisingProvider:
    """Provider double for arbitrary provider failures."""

    def __init__(self, failure: Exception) -> None:
        self.failure = failure

    async def invoke(
        self,
        request: ModelRequest,
        *,
        model: str,
    ) -> ModelResponse:
        raise self.failure

    async def invoke_structured(
        self,
        request: ModelRequest,
        response_model: type[BaseModel],
        *,
        model: str,
    ) -> object:
        raise self.failure


def test_all_logical_profiles_route_to_their_exact_configured_models() -> None:
    profiles = tuple(ModelProfile)
    provider = MockModelProvider(responses=[profile.value for profile in profiles])
    gateway = ModelGateway(
        routes={
            profile: ModelRoute(
                profile=profile,
                provider="mock",
                model=f"configured-{profile.value.lower()}",
            )
            for profile in profiles
        },
        providers={"mock": provider},
    )

    async def invoke_all() -> list[ModelResponse]:
        return list(
            await asyncio.gather(
                *(gateway.invoke(make_request(profile)) for profile in profiles)
            )
        )

    responses = run_async(invoke_all())

    assert [response.content for response in responses] == [
        profile.value for profile in profiles
    ]
    assert [response.model for response in responses] == [
        f"configured-{profile.value.lower()}" for profile in profiles
    ]
    assert [invocation.profile for invocation in provider.history] == list(profiles)


def test_profile_aliases_cannot_create_duplicate_routes() -> None:
    first = ModelRoute(
        profile=ModelProfile.CHEAP,
        provider="mock",
        model="first",
    )
    second = first.model_copy(update={"model": "second"})

    with pytest.raises(ModelRouteConfigurationError):
        ModelGateway(
            routes={
                ModelProfile.CHEAP: first,
                "cheap": second,
            }
        )


def test_unknown_request_profile_is_rejected_before_route_lookup_or_provider() -> None:
    provider = MockModelProvider(responses=["must not run"])
    gateway = make_gateway(provider, provider_name="mock")
    invalid_request = ModelRequest.model_construct(
        task=ModelTask.REQUEST_UNDERSTANDING,
        profile="UNKNOWN",
        messages=[ModelMessage(role=ModelRole.USER, content="hello")],
        metadata={},
    )

    with pytest.raises(ValidationError):
        run_async(gateway.invoke(invalid_request))

    assert provider.invocation_count == 0


def test_gateway_validates_a_structured_response_envelope_from_a_provider() -> None:
    metadata = ModelResponse(
        content='{"answer":"ignored raw text"}',
        provider="adapter",
        model="adapter-cheap",
        finish_reason="stop",
        usage=ModelUsage(input_tokens=3, output_tokens=2, total_tokens=5),
        latency_ms=8.5,
        request_id="structured-1",
    )
    provider = DirectStructuredProvider(
        StructuredModelResponse[StructuredAnswer](
            parsed=StructuredAnswer(answer="validated"),
            response=metadata,
        )
    )

    result = run_async(
        make_gateway(provider).invoke_structured(
            make_request(), StructuredAnswer
        )
    )

    assert isinstance(result, StructuredModelResponse)
    assert result.parsed.answer == "validated"
    assert result.response == metadata
    assert result.response.usage == ModelUsage(
        input_tokens=3,
        output_tokens=2,
        total_tokens=5,
    )


def test_gateway_revalidates_structured_wrapper_metadata() -> None:
    invalid_metadata = ModelResponse.model_construct(
        content="",
        provider="adapter",
        model="adapter-cheap",
        latency_ms=math.nan,
    )
    invalid_wrapper = StructuredModelResponse[StructuredAnswer].model_construct(
        parsed=StructuredAnswer(answer="payload"),
        response=invalid_metadata,
    )

    with pytest.raises(ModelStructuredOutputError) as error:
        run_async(
            make_gateway(DirectStructuredProvider(invalid_wrapper)).invoke_structured(
                make_request(), StructuredAnswer
            )
        )

    assert isinstance(error.value.__cause__, ValidationError)
    assert "ModelResponse" in str(error.value.__cause__)


def test_gateway_revalidates_structured_wrapper_payload_against_caller_schema() -> None:
    invalid_wrapper = StructuredModelResponse[StructuredAnswer].model_construct(
        parsed={"answer": 42},
        response=ModelResponse(
            content="",
            provider="adapter",
            model="adapter-cheap",
        ),
    )

    with pytest.raises(ModelStructuredOutputError) as error:
        run_async(
            make_gateway(DirectStructuredProvider(invalid_wrapper)).invoke_structured(
                make_request(), StructuredAnswer
            )
        )

    assert isinstance(error.value.__cause__, ValidationError)
    assert "StructuredAnswer" in str(error.value)


class OutputMode(StrEnum):
    READ = "READ"
    WRITE = "WRITE"


class EnumOutput(BaseModel):
    mode: OutputMode


def test_structured_output_rejects_an_unknown_enum_value() -> None:
    provider = MockModelProvider(structured_responses=[{"mode": "DELETE"}])

    with pytest.raises(ModelStructuredOutputError) as error:
        run_async(
            make_gateway(provider, provider_name="mock").invoke_structured(
                make_request(), EnumOutput
            )
        )

    assert "EnumOutput" in str(error.value)
    assert isinstance(error.value.__cause__, ValidationError)


@pytest.mark.parametrize("failure_type", [ValueError, LookupError, OSError])
def test_arbitrary_text_provider_failures_are_typed_and_chained(
    failure_type: type[Exception],
) -> None:
    failure = failure_type("provider failed")

    with pytest.raises(ModelInvocationError) as error:
        run_async(
            make_gateway(
                RaisingProvider(failure), provider_name="adapter"
            ).invoke(make_request())
        )

    assert error.value.__cause__ is failure


@pytest.mark.parametrize("failure_type", [ValueError, LookupError, OSError])
def test_arbitrary_structured_provider_failures_are_typed_and_chained(
    failure_type: type[Exception],
) -> None:
    failure = failure_type("structured provider failed")

    with pytest.raises(ModelInvocationError) as error:
        run_async(
            make_gateway(
                RaisingProvider(failure), provider_name="adapter"
            ).invoke_structured(make_request(), StructuredAnswer)
        )

    assert error.value.__cause__ is failure


def test_parallel_structured_calls_consume_dedicated_queue_without_crossing() -> None:
    call_count = 24
    provider = MockModelProvider(
        responses=["text queue remains"],
        structured_responses=[
            {"answer": f"structured-{index}"} for index in range(call_count)
        ],
    )
    gateway = make_gateway(provider, provider_name="mock")
    requests = [
        make_request(metadata={"call_index": index})
        for index in range(call_count)
    ]

    async def invoke_all() -> list[str]:
        results = await asyncio.gather(
            *(
                gateway.invoke_structured(item, StructuredAnswer)
                for item in requests
            )
        )
        return [result.parsed.answer for result in results]

    assert run_async(invoke_all()) == [
        f"structured-{index}" for index in range(call_count)
    ]
    assert provider.remaining_structured_responses == 0
    assert provider.remaining_responses == 1
    assert [
        invocation.request.metadata["call_index"]
        for invocation in provider.history
    ] == list(range(call_count))


def test_all_history_aliases_are_detached_deep_snapshots() -> None:
    provider = MockModelProvider(responses=["reply"])
    request = make_request(metadata={"nested": {"original": True}})
    run_async(make_gateway(provider, provider_name="mock").invoke(request))

    for snapshot in (provider.history, provider.invocations, provider.calls):
        snapshot[0].request.metadata["nested"]["changed"] = True  # type: ignore[index]
        snapshot[0].request.messages[0].content = "changed"
        snapshot[0].request.messages.append(
            ModelMessage(role=ModelRole.SYSTEM, content="extra")
        )
        snapshot.clear()

    request.metadata["nested"]["caller_changed"] = True
    request.messages[0].content = "caller changed"
    history = provider.history

    assert provider.invocation_count == 1
    assert len(history) == 1
    assert history[0].request.metadata == {"nested": {"original": True}}
    assert history[0].request.messages[0].content == "hello"
    assert len(history[0].request.messages) == 1


def test_separate_providers_and_gateways_do_not_share_queues_or_history() -> None:
    first_provider = MockModelProvider(responses=["first"])
    second_provider = MockModelProvider(responses=["second"])
    first_gateway = make_gateway(first_provider, provider_name="mock")
    second_gateway = make_gateway(second_provider, provider_name="mock")

    assert (
        run_async(
            first_gateway.invoke(make_request(metadata={"owner": "first"}))
        ).content
        == "first"
    )
    assert (
        run_async(
            second_gateway.invoke(make_request(metadata={"owner": "second"}))
        ).content
        == "second"
    )

    assert first_provider.invocation_count == 1
    assert second_provider.invocation_count == 1
    assert first_provider.history[0].request.metadata == {"owner": "first"}
    assert second_provider.history[0].request.metadata == {"owner": "second"}
