"""Developer tests for the provider-neutral model gateway contract."""

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
    ModelProviderAlreadyRegisteredError,
    ModelProviderNotFoundError,
    ModelRequest,
    ModelResponse,
    ModelRole,
    ModelRoute,
    ModelRouteConfigurationError,
    ModelRouteNotFoundError,
    ModelStructuredOutputError,
    ModelTask,
    ModelUsage,
    StructuredModelResponse,
)

T = TypeVar("T")


def run_async(operation: Coroutine[Any, Any, T]) -> T:
    """Run an async gateway operation without requiring an extra test plugin."""

    return asyncio.run(operation)


def request(
    profile: ModelProfile = ModelProfile.CHEAP,
    *,
    task: ModelTask = ModelTask.REQUEST_UNDERSTANDING,
) -> ModelRequest:
    return ModelRequest(
        task=task,
        profile=profile,
        messages=[ModelMessage(role=ModelRole.USER, content="hello")],
        metadata={"thread_id": "thread-123", "node": "understand_request"},
    )


def route(
    profile: ModelProfile,
    *,
    provider: str = "mock",
    model: str | None = None,
) -> ModelRoute:
    return ModelRoute(
        profile=profile,
        provider=provider,
        model=model or f"mock-{profile.name.lower()}",
    )


def gateway(
    provider: MockModelProvider,
    *profiles: ModelProfile,
) -> ModelGateway:
    selected = profiles or (ModelProfile.CHEAP,)
    return ModelGateway(
        routes={profile: route(profile) for profile in selected},
        providers={"mock": provider},
    )


def test_profiles_and_tasks_are_provider_neutral() -> None:
    assert {profile.value for profile in ModelProfile} == {
        "CHEAP",
        "STRONG",
        "FALLBACK",
    }
    assert {task.value for task in ModelTask} == {
        "REQUEST_UNDERSTANDING",
        "ACTION_DECISION",
        "TOOL_SELECTION",
        "TOOL_RESULT_REVIEW",
        "CLARIFICATION",
        "RESPONSE_GENERATION",
        "HANDOFF_GENERATION",
    }
    assert {role.value for role in ModelRole} == {
        "SYSTEM",
        "USER",
        "ASSISTANT",
        "TOOL",
    }


def test_structured_response_contract_is_publicly_exported() -> None:
    from opsmind import StructuredModelResponse as RootStructuredModelResponse

    assert RootStructuredModelResponse is StructuredModelResponse


def test_request_requires_at_least_one_message_and_json_metadata() -> None:
    with pytest.raises(ValidationError):
        ModelRequest(
            task=ModelTask.RESPONSE_GENERATION,
            profile=ModelProfile.CHEAP,
            messages=[],
        )

    with pytest.raises(ValidationError):
        ModelRequest(
            task=ModelTask.RESPONSE_GENERATION,
            profile=ModelProfile.CHEAP,
            messages=[ModelMessage(role=ModelRole.USER, content="hello")],
            metadata={"score": math.nan},
        )


def test_usage_and_latency_metadata_are_bounded() -> None:
    with pytest.raises(ValidationError):
        ModelUsage(input_tokens=-1)
    with pytest.raises(ValidationError):
        ModelResponse(
            content="hello",
            provider="mock",
            model="mock-cheap",
            latency_ms=math.inf,
        )
    with pytest.raises(ValidationError):
        ModelResponse(
            content="hello",
            provider="mock",
            model="mock-cheap",
            latency_ms=-0.1,
        )


def test_cheap_and_strong_profiles_route_to_their_explicit_models() -> None:
    provider = MockModelProvider(responses=["cheap reply", "strong reply"])
    model_gateway = gateway(provider, ModelProfile.CHEAP, ModelProfile.STRONG)

    cheap = run_async(model_gateway.invoke(request(ModelProfile.CHEAP)))
    strong = run_async(model_gateway.invoke(request(ModelProfile.STRONG)))

    assert cheap.content == "cheap reply"
    assert cheap.model == "mock-cheap"
    assert strong.content == "strong reply"
    assert strong.model == "mock-strong"


def test_missing_route_is_a_typed_gateway_error() -> None:
    model_gateway = gateway(MockModelProvider(responses=["unused"]))

    with pytest.raises(ModelRouteNotFoundError) as error:
        run_async(model_gateway.invoke(request(ModelProfile.STRONG)))

    assert error.value.profile is ModelProfile.STRONG


def test_missing_provider_is_a_typed_gateway_error() -> None:
    model_gateway = ModelGateway(
        routes={ModelProfile.CHEAP: route(ModelProfile.CHEAP, provider="absent")},
    )

    with pytest.raises(ModelProviderNotFoundError) as error:
        run_async(model_gateway.invoke(request()))

    assert "absent" in str(error.value)


def test_structured_output_is_validated_to_a_pydantic_instance() -> None:
    class ExampleOutput(BaseModel):
        answer: str
        confidence: float

    provider = MockModelProvider(
        structured_responses=[{"answer": "ready", "confidence": 0.95}]
    )
    model_gateway = gateway(provider)

    result = run_async(model_gateway.invoke_structured(request(), ExampleOutput))

    assert isinstance(result, StructuredModelResponse)
    assert isinstance(result.parsed, ExampleOutput)
    assert result.parsed.answer == "ready"
    assert result.parsed.confidence == 0.95
    assert result.response.provider == "mock"
    assert result.response.model == "mock-cheap"


def test_invalid_structured_output_has_a_specific_error() -> None:
    class StrictOutput(BaseModel):
        model_config = ConfigDict(extra="forbid")

        answer: str
        confidence: float

    provider = MockModelProvider(
        structured_responses=[
            {"answer": "ready", "confidence": "not-a-number", "extra": True}
        ]
    )
    model_gateway = gateway(provider)

    with pytest.raises(ModelStructuredOutputError) as error:
        run_async(model_gateway.invoke_structured(request(), StrictOutput))

    assert "StrictOutput" in str(error.value)


def test_structured_output_preserves_provider_response_metadata() -> None:
    class ExampleOutput(BaseModel):
        answer: str

    provider = MockModelProvider(
        structured_responses=[
            ModelResponse(
                content='{"answer":"ready"}',
                provider="mock",
                model="mock-cheap",
                finish_reason="stop",
                usage=ModelUsage(
                    input_tokens=4,
                    output_tokens=2,
                    total_tokens=6,
                ),
                latency_ms=12.5,
                request_id="request-1",
            )
        ]
    )
    model_gateway = gateway(provider)
    result = run_async(model_gateway.invoke_structured(request(), ExampleOutput))

    assert result.parsed.answer == "ready"
    assert result.response.provider == "mock"
    assert result.response.model == "mock-cheap"
    assert result.response.finish_reason == "stop"
    assert result.response.usage == ModelUsage(
        input_tokens=4,
        output_tokens=2,
        total_tokens=6,
    )
    assert result.response.latency_ms == 12.5
    assert result.response.request_id == "request-1"


def test_structured_value_convenience_returns_only_the_validated_model() -> None:
    class ExampleOutput(BaseModel):
        answer: str

    provider = MockModelProvider(structured_responses=[{"answer": "ready"}])
    model_gateway = gateway(provider)

    result = run_async(
        model_gateway.invoke_structured_value(request(), ExampleOutput)
    )

    assert isinstance(result, ExampleOutput)
    assert result.answer == "ready"


def test_mock_history_records_request_profile_task_messages_and_model() -> None:
    provider = MockModelProvider(responses=["reply"])
    model_gateway = gateway(provider)
    incoming = request(task=ModelTask.ACTION_DECISION)

    run_async(model_gateway.invoke(incoming))

    assert provider.invocation_count == 1
    invocation = provider.history[0]
    assert invocation.request == incoming
    assert invocation.profile is ModelProfile.CHEAP
    assert invocation.task is ModelTask.ACTION_DECISION
    assert invocation.messages == incoming.messages
    assert invocation.model == "mock-cheap"


def test_mock_queue_is_consumed_in_order_and_exhaustion_is_typed() -> None:
    provider = MockModelProvider(responses=["first"])
    model_gateway = gateway(provider)

    assert run_async(model_gateway.invoke(request())).content == "first"
    with pytest.raises(MockResponseQueueExhaustedError):
        run_async(model_gateway.invoke(request()))

    assert provider.call_count == 2


def test_provider_exception_is_wrapped_as_model_invocation_error() -> None:
    provider = MockModelProvider(responses=[RuntimeError("provider offline")])
    model_gateway = gateway(provider)

    with pytest.raises(ModelInvocationError) as error:
        run_async(model_gateway.invoke(request()))

    assert isinstance(error.value.__cause__, RuntimeError)


def test_duplicate_provider_registration_is_rejected() -> None:
    provider = MockModelProvider()
    model_gateway = ModelGateway()
    model_gateway.register_provider("mock", provider)

    with pytest.raises(ModelProviderAlreadyRegisteredError):
        model_gateway.register_provider("mock", provider)


def test_route_configuration_rejects_mismatched_profile_keys() -> None:
    with pytest.raises(ModelRouteConfigurationError):
        ModelGateway(
            routes={
                "cheap": route(ModelProfile.STRONG),
            }
        )


def test_route_configuration_accepts_string_profile_keys() -> None:
    model_gateway = ModelGateway(
        routes={"cheap": route(ModelProfile.CHEAP)},
        providers={"mock": MockModelProvider(responses=["ok"])},
    )

    assert run_async(model_gateway.invoke(request())).content == "ok"


def test_routes_property_returns_detached_route_models() -> None:
    provider = MockModelProvider(responses=["ok"])
    model_gateway = gateway(provider)

    exposed_routes = model_gateway.routes
    exposed_routes[ModelProfile.CHEAP].model = "tampered-model"
    exposed_routes[ModelProfile.CHEAP].provider = "tampered-provider"

    response = run_async(model_gateway.invoke(request()))

    assert response.model == "mock-cheap"
    assert model_gateway.routes[ModelProfile.CHEAP].model == "mock-cheap"
    assert model_gateway.routes[ModelProfile.CHEAP].provider == "mock"


def test_mock_enqueue_alias_supports_queued_text_responses() -> None:
    provider = MockModelProvider()
    provider.enqueue("ok")

    assert run_async(gateway(provider).invoke(request())).content == "ok"
