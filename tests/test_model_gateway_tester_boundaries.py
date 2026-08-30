"""Independent adversarial and boundary coverage for the model gateway."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Coroutine
from typing import Any, TypeVar

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from opsmind.models import (
    MockModelProvider,
    MockResponseQueueExhaustedError,
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
    """Run one async gateway operation in a test without an extra plugin."""

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
        metadata=(
            metadata if metadata is not None else {"thread_id": "tester-thread"}
        ),
    )


def make_gateway(
    provider: MockModelProvider,
    profile: ModelProfile = ModelProfile.CHEAP,
) -> ModelGateway:
    routes: dict[ModelProfile | str, ModelRoute] = {
        profile: ModelRoute(
            profile=profile,
            provider="mock",
            model=f"mock-{profile.name.lower()}",
        )
    }
    return ModelGateway(
        routes=routes,
        providers={"mock": provider},
    )


def test_empty_messages_are_rejected_before_a_provider_can_run() -> None:
    provider = MockModelProvider(responses=["should not be consumed"])
    model_gateway = make_gateway(provider)

    with pytest.raises(ValidationError):
        run_async(
            model_gateway.invoke(
                ModelRequest.model_construct(
                    task=ModelTask.REQUEST_UNDERSTANDING,
                    profile=ModelProfile.CHEAP,
                    messages=[],
                    metadata={},
                )
            )
        )

    assert provider.invocation_count == 0


@pytest.mark.parametrize(
    "route_config",
    [
        {"profile": "unknown", "provider": "mock", "model": "mock"},
        {"profile": "cheap", "provider": "", "model": "mock"},
        {"profile": "cheap", "provider": "mock", "model": " "},
        {"profile": "cheap", "provider": "mock"},
        {"provider": "mock", "model": "mock"},
        {
            "profile": "cheap",
            "provider": "mock",
            "model": "mock",
            "unexpected": True,
        },
    ],
)
def test_malformed_route_entries_are_typed_configuration_errors(
    route_config: dict[str, object],
) -> None:
    with pytest.raises(ModelRouteConfigurationError) as error:
        ModelGateway(routes=[route_config])

    assert isinstance(error.value.__cause__, ValidationError)


def test_unknown_profile_mapping_key_is_a_typed_configuration_error() -> None:
    with pytest.raises(ModelRouteConfigurationError) as error:
        ModelGateway(
            routes={
                "unknown": ModelRoute(
                    profile=ModelProfile.CHEAP,
                    provider="mock",
                    model="mock-cheap",
                )
            }
        )

    assert "unknown model profile" in str(error.value)


def test_duplicate_routes_are_rejected_without_overwriting_the_first_route() -> None:
    first = ModelRoute(
        profile=ModelProfile.CHEAP,
        provider="mock",
        model="first-model",
    )
    second = first.model_copy(update={"model": "second-model"})

    with pytest.raises(ModelRouteConfigurationError):
        ModelGateway(routes=[first, second])


def test_request_metadata_accepts_the_json_value_domain() -> None:
    metadata = {
        "empty": "",
        "integer": -3,
        "float": -0.25,
        "boolean": False,
        "null": None,
        "array": [0, 1.5, True, None, "text"],
        "object": {"nested": {"enabled": True}},
    }

    request = make_request(metadata=metadata)

    assert request.metadata == metadata


@pytest.mark.parametrize("non_finite", [math.nan, math.inf, -math.inf])
def test_nested_non_finite_request_metadata_is_rejected(
    non_finite: float,
) -> None:
    with pytest.raises(ValidationError):
        make_request(
            metadata={
                "trace": {
                    "samples": [{"score": non_finite}],
                }
            }
        )


@pytest.mark.parametrize("field", ["input_tokens", "output_tokens", "total_tokens"])
@pytest.mark.parametrize("value", [-1, math.nan, math.inf, -math.inf])
def test_token_usage_rejects_negative_and_non_finite_values(
    field: str,
    value: float | int,
) -> None:
    with pytest.raises(ValidationError):
        ModelUsage(**{field: value})


@pytest.mark.parametrize("field", ["input_tokens", "output_tokens", "total_tokens"])
@pytest.mark.parametrize("value", [True, False])
def test_token_usage_rejects_boolean_values(field: str, value: bool) -> None:
    with pytest.raises(ValidationError):
        ModelUsage(**{field: value})


@pytest.mark.parametrize("latency_ms", [-1.0, math.nan, math.inf, -math.inf])
def test_latency_rejects_negative_and_non_finite_values(latency_ms: float) -> None:
    with pytest.raises(ValidationError):
        ModelResponse(
            content="reply",
            provider="mock",
            model="mock-cheap",
            latency_ms=latency_ms,
        )


def test_invalid_provider_response_metadata_is_wrapped_as_invocation_error() -> None:
    provider = MockModelProvider(
        responses=[{"content": "reply", "latency_ms": math.nan}]
    )

    with pytest.raises(ModelInvocationError) as error:
        run_async(make_gateway(provider).invoke(make_request()))

    assert isinstance(error.value.__cause__, ValidationError)


class StructuredAnswer(BaseModel):
    answer: str
    confidence: float


@pytest.mark.parametrize(
    "payload",
    [
        "{not valid JSON",
        {"answer": "missing confidence"},
        {"answer": ["wrong scalar type"], "confidence": 0.5},
        None,
    ],
)
def test_malformed_structured_payload_is_a_specific_error(
    payload: object,
) -> None:
    provider = MockModelProvider(structured_responses=[payload])

    with pytest.raises(ModelStructuredOutputError) as error:
        run_async(
            make_gateway(provider).invoke_structured(
                make_request(), StructuredAnswer
            )
        )

    assert "StructuredAnswer" in str(error.value)
    assert isinstance(error.value.__cause__, ValidationError)


def test_structured_provider_exception_is_typed_and_preserves_the_cause() -> None:
    provider = MockModelProvider(
        structured_responses=[RuntimeError("structured provider offline")]
    )

    with pytest.raises(ModelInvocationError) as error:
        run_async(
            make_gateway(provider).invoke_structured(
                make_request(), StructuredAnswer
            )
        )

    assert isinstance(error.value.__cause__, RuntimeError)


def test_structured_output_honors_a_permissive_caller_schema() -> None:
    class PermissiveOutput(BaseModel):
        answer: str

    provider = MockModelProvider(
        structured_responses=[{"answer": "ok", "provider_field": "ignored"}]
    )

    result = run_async(
        make_gateway(provider).invoke_structured(make_request(), PermissiveOutput)
    )

    assert isinstance(result, StructuredModelResponse)
    assert result.parsed.answer == "ok"
    assert result.parsed.model_extra is None


def test_structured_output_honors_an_allow_extra_caller_schema() -> None:
    class AllowExtraOutput(BaseModel):
        model_config = ConfigDict(extra="allow")

        answer: str

    provider = MockModelProvider(
        structured_responses=[{"answer": "ok", "provider_field": "retained"}]
    )

    result = run_async(
        make_gateway(provider).invoke_structured(make_request(), AllowExtraOutput)
    )

    assert isinstance(result, StructuredModelResponse)
    assert result.parsed.answer == "ok"
    assert result.parsed.model_extra == {"provider_field": "retained"}


def test_structured_output_honors_a_forbid_extra_caller_schema() -> None:
    class ForbidExtraOutput(BaseModel):
        model_config = ConfigDict(extra="forbid")

        answer: str

    provider = MockModelProvider(
        structured_responses=[{"answer": "ok", "provider_field": "rejected"}]
    )

    with pytest.raises(ModelStructuredOutputError):
        run_async(
            make_gateway(provider).invoke_structured(
                make_request(), ForbidExtraOutput
            )
        )


def test_dedicated_structured_queue_exhaustion_does_not_consume_text_queue() -> None:
    provider = MockModelProvider(
        responses=["text remains"],
        structured_responses=[],
    )
    model_gateway = make_gateway(provider)

    with pytest.raises(MockResponseQueueExhaustedError):
        run_async(
            model_gateway.invoke_structured(make_request(), StructuredAnswer)
        )

    assert provider.remaining_structured_responses == 0
    assert provider.remaining_responses == 1
    assert provider.invocation_count == 1


def test_concurrent_calls_keep_distinct_requests_and_history_snapshots() -> None:
    call_count = 16
    provider = MockModelProvider(
        responses=[f"reply-{index}" for index in range(call_count)]
    )
    model_gateway = make_gateway(provider)
    requests = [
        make_request(metadata={"call_index": index})
        for index in range(call_count)
    ]

    async def invoke_all() -> list[ModelResponse]:
        results = await asyncio.gather(
            *(model_gateway.invoke(item) for item in requests)
        )
        return list(results)

    responses = run_async(invoke_all())

    assert [response.content for response in responses] == [
        f"reply-{index}" for index in range(call_count)
    ]
    assert provider.invocation_count == call_count
    assert len({id(invocation.request) for invocation in provider.history}) == (
        call_count
    )
    history_message_ids = {
        id(invocation.request.messages) for invocation in provider.history
    }
    assert len(history_message_ids) == call_count
    assert [
        invocation.request.metadata["call_index"]
        for invocation in provider.history
    ] == list(range(call_count))

    requests[0].metadata["after_call_mutation"] = True
    assert "after_call_mutation" not in provider.history[0].request.metadata


def test_history_access_returns_detached_records() -> None:
    provider = MockModelProvider(responses=["reply"])
    model_gateway = make_gateway(provider)

    run_async(model_gateway.invoke(make_request(metadata={"mutable": True})))
    history = provider.history
    history[0].request.metadata["changed"] = True
    history.clear()

    assert provider.invocation_count == 1
    assert "changed" not in provider.history[0].request.metadata
