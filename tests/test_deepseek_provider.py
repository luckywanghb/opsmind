from __future__ import annotations

import asyncio
import json
import math
import traceback
from collections import deque
from enum import StrEnum

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from opsmind.models import (
    DeepSeekProvider,
    DeepSeekSettings,
    ModelInvocationError,
    ModelMessage,
    ModelProfile,
    ModelRequest,
    ModelRole,
    ModelStructuredOutputError,
    ModelTask,
    build_deepseek_gateway,
)


class Choice(StrEnum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"


class StructuredAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    choice: Choice
    explanation: str


class FakeResponses:
    def __init__(self, *results: object) -> None:
        self.results = deque(results)
        self.calls: list[dict[str, object]] = []

    async def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        result = self.results.popleft()
        if isinstance(result, BaseException):
            raise result
        if callable(result):
            produced = result()
            if asyncio.iscoroutine(produced):
                return await produced
            return produced
        return result


class FakeClient:
    def __init__(self, *results: object) -> None:
        self.responses = FakeResponses(*results)


class Clock:
    def __init__(self, *values: float) -> None:
        self.values = deque(values)

    def __call__(self) -> float:
        return self.values.popleft()


def settings(**overrides: object) -> DeepSeekSettings:
    return DeepSeekSettings.model_validate(
        {
            "api_key": "test-secret-value",
            **overrides,
        }
    )


def request(*roles: ModelRole) -> ModelRequest:
    return ModelRequest(
        task=ModelTask.REQUEST_UNDERSTANDING,
        profile=ModelProfile.CHEAP,
        messages=[
            ModelMessage(role=role, content=f"content-{index}")
            for index, role in enumerate(roles)
        ],
        metadata={"thread_id": "not-provider-input", "node": "test"},
    )


def response(
    content: str = "hello",
    *,
    model: str = "configured-model",
    usage: object = None,
    status: object = "completed",
    response_id: object = "resp-123",
    request_id: object = None,
) -> dict[str, object]:
    result: dict[str, object] = {
        "output_text": content,
        "model": model,
        "status": status,
        "id": response_id,
    }
    if usage is not None:
        result["usage"] = usage
    if request_id is not None:
        result["_request_id"] = request_id
    return result


def test_settings_require_api_key() -> None:
    with pytest.raises(ValidationError):
        DeepSeekSettings.from_env({})


@pytest.mark.parametrize("key", ["", " ", "\t\n"])
def test_settings_reject_blank_api_key(key: str) -> None:
    with pytest.raises(ValidationError):
        DeepSeekSettings.from_env({"DEEPSEEK_API_KEY": key})


def test_settings_defaults_and_configurable_models() -> None:
    configured = DeepSeekSettings.from_env(
        {
            "DEEPSEEK_API_KEY": "secret",
            "OPSMIND_CHEAP_MODEL": "cheap-custom",
            "OPSMIND_STRONG_MODEL": "strong-custom",
        }
    )

    assert configured.base_url == "https://api.deepseek.com"
    assert configured.cheap_model == "cheap-custom"
    assert configured.strong_model == "strong-custom"
    assert configured.reasoning_effort == "none"


@pytest.mark.parametrize("timeout", ["0", "-1", "nan", "inf", "not-a-number"])
def test_settings_reject_malformed_timeout(timeout: str) -> None:
    with pytest.raises(ValidationError):
        DeepSeekSettings.from_env(
            {
                "DEEPSEEK_API_KEY": "secret",
                "DEEPSEEK_TIMEOUT_SECONDS": timeout,
            }
        )


def test_settings_and_provider_do_not_reveal_secret() -> None:
    configured = settings()
    provider = DeepSeekProvider(configured, client=FakeClient())

    assert "test-secret-value" not in repr(configured)
    assert "test-secret-value" not in repr(configured.model_dump())
    assert "test-secret-value" not in configured.model_dump_json()
    assert "test-secret-value" not in repr(provider)


@pytest.mark.asyncio
async def test_text_request_maps_supported_roles_model_and_thinking() -> None:
    client = FakeClient(response())
    provider = DeepSeekProvider(settings(), client=client, clock=Clock(1.0, 1.01))

    await provider.invoke(
        request(ModelRole.SYSTEM, ModelRole.USER, ModelRole.ASSISTANT),
        model="configured-model",
    )

    call = client.responses.calls[0]
    assert call["model"] == "configured-model"
    assert call["reasoning"] == {"effort": "none"}
    assert call["input"] == [
        {"type": "message", "role": "system", "content": "content-0"},
        {"type": "message", "role": "user", "content": "content-1"},
        {"type": "message", "role": "assistant", "content": "content-2"},
    ]
    assert "metadata" not in call
    assert "text" not in call


@pytest.mark.asyncio
async def test_configured_reasoning_effort_is_forwarded() -> None:
    client = FakeClient(response())
    provider = DeepSeekProvider(
        settings(reasoning_effort="low"), client=client, clock=Clock(0.0, 0.1)
    )

    await provider.invoke(request(ModelRole.USER), model="configured-model")

    assert client.responses.calls[0]["reasoning"] == {"effort": "low"}


@pytest.mark.asyncio
async def test_unsupported_tool_role_fails_before_transport() -> None:
    client = FakeClient(response())
    provider = DeepSeekProvider(settings(), client=client)

    with pytest.raises(ModelInvocationError, match="does not support role"):
        await provider.invoke(request(ModelRole.TOOL), model="configured-model")

    assert client.responses.calls == []


@pytest.mark.asyncio
async def test_text_response_maps_content_and_metadata() -> None:
    client = FakeClient(
        response(
            "mapped content",
            usage={"input_tokens": 3, "output_tokens": 4, "total_tokens": 7},
            request_id="request-header-id",
        )
    )
    provider = DeepSeekProvider(settings(), client=client, clock=Clock(4.0, 4.025))

    result = await provider.invoke(
        request(ModelRole.USER), model="configured-model"
    )

    assert result.content == "mapped content"
    assert result.provider == "deepseek"
    assert result.model == "configured-model"
    assert result.finish_reason == "completed"
    assert result.request_id == "request-header-id"
    assert result.latency_ms == pytest.approx(25.0)
    assert result.usage is not None
    assert result.usage.model_dump() == {
        "input_tokens": 3,
        "output_tokens": 4,
        "total_tokens": 7,
    }


@pytest.mark.asyncio
async def test_response_id_is_not_mislabeled_and_usage_can_be_missing() -> None:
    client = FakeClient(response(response_id="response-id"))
    provider = DeepSeekProvider(settings(), client=client, clock=Clock(0.0, 0.0))

    result = await provider.invoke(
        request(ModelRole.USER), model="configured-model"
    )

    assert result.request_id is None
    assert result.usage is None


@pytest.mark.asyncio
async def test_text_can_be_extracted_from_response_output_items() -> None:
    client = FakeClient(
        {
            "model": "configured-model",
            "status": "completed",
            "output": [
                {"type": "reasoning", "content": [{"type": "reasoning_text"}]},
                {
                    "type": "message",
                    "content": [
                        {"type": "output_text", "text": "first"},
                        {"type": "output_text", "text": " second"},
                    ],
                },
            ],
        }
    )
    provider = DeepSeekProvider(settings(), client=client, clock=Clock(0.0, 0.1))

    result = await provider.invoke(
        request(ModelRole.USER), model="configured-model"
    )

    assert result.content == "first second"


@pytest.mark.asyncio
@pytest.mark.parametrize("content", ["", " ", "\n"])
async def test_empty_text_response_is_an_invocation_error(content: str) -> None:
    provider = DeepSeekProvider(
        settings(),
        client=FakeClient(response(content)),
        clock=Clock(0.0, 0.1),
    )

    with pytest.raises(ModelInvocationError, match="DeepSeek model invocation failed"):
        await provider.invoke(request(ModelRole.USER), model="configured-model")


@pytest.mark.asyncio
async def test_structured_request_supplies_pydantic_json_schema_and_validates() -> None:
    payload = {"choice": "ACCEPT", "explanation": "valid"}
    client = FakeClient(response(json.dumps(payload)))
    provider = DeepSeekProvider(settings(), client=client, clock=Clock(0.0, 0.02))

    result = await provider.invoke_structured(
        request(ModelRole.SYSTEM, ModelRole.USER),
        StructuredAnswer,
        model="configured-model",
    )

    assert result.parsed == StructuredAnswer.model_validate(payload)
    assert result.response.provider == "deepseek"
    assert result.response.content == json.dumps(payload)
    assert client.responses.calls[0]["text"] == {
        "format": {
            "type": "json_schema",
            "name": "StructuredAnswer",
            "schema": StructuredAnswer.model_json_schema(),
        }
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content",
    [
        "",
        " ",
        "not-json",
        '{"choice":"ACCEPT"',
        '{"choice":"ACCEPT"}',
        '{"choice":"WRONG","explanation":"x"}',
        '{"choice":"ACCEPT","explanation":"x","extra":true}',
    ],
)
async def test_invalid_structured_output_raises_structured_error(content: str) -> None:
    provider = DeepSeekProvider(
        settings(),
        client=FakeClient(response(content)),
        clock=Clock(0.0, 0.01),
    )

    with pytest.raises(ModelStructuredOutputError):
        await provider.invoke_structured(
            request(ModelRole.USER), StructuredAnswer, model="configured-model"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [TimeoutError(), RuntimeError("401"), RuntimeError("429"), RuntimeError("500")],
)
async def test_transport_failures_map_to_invocation_error(failure: Exception) -> None:
    provider = DeepSeekProvider(settings(), client=FakeClient(failure))

    with pytest.raises(
        ModelInvocationError, match="DeepSeek model invocation failed"
    ) as exc:
        await provider.invoke(request(ModelRole.USER), model="configured-model")

    assert exc.value.__cause__ is None
    assert "test-secret-value" not in str(exc.value)


@pytest.mark.asyncio
async def test_transport_secret_is_absent_from_chained_traceback() -> None:
    secret = "transport-secret-must-not-appear"
    provider = DeepSeekProvider(
        settings(api_key=secret),
        client=FakeClient(RuntimeError(f"Authorization: Bearer {secret}")),
    )

    with pytest.raises(ModelInvocationError) as exc:
        await provider.invoke(request(ModelRole.USER), model="configured-model")

    rendered = "".join(traceback.format_exception(exc.value))
    assert secret not in rendered
    assert exc.value.__cause__ is None
    assert exc.value.__context__ is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_response",
    [
        object(),
        {"output_text": 123, "model": "configured-model"},
        response(model="different-model"),
        response(usage={"input_tokens": -1}),
        response(status=123),
        response(request_id=123),
    ],
)
async def test_malformed_text_provider_response_is_invocation_error(
    bad_response: object,
) -> None:
    provider = DeepSeekProvider(
        settings(), client=FakeClient(bad_response), clock=Clock(0.0, 0.01)
    )

    with pytest.raises(ModelInvocationError):
        await provider.invoke(request(ModelRole.USER), model="configured-model")


@pytest.mark.asyncio
async def test_invalid_latency_is_rejected() -> None:
    provider = DeepSeekProvider(
        settings(),
        client=FakeClient(response()),
        clock=Clock(0.0, math.nan),
    )

    with pytest.raises(ModelInvocationError):
        await provider.invoke(request(ModelRole.USER), model="configured-model")


@pytest.mark.asyncio
async def test_async_cancellation_is_not_wrapped() -> None:
    provider = DeepSeekProvider(
        settings(), client=FakeClient(asyncio.CancelledError())
    )

    with pytest.raises(asyncio.CancelledError):
        await provider.invoke(request(ModelRole.USER), model="configured-model")


@pytest.mark.asyncio
async def test_shared_provider_supports_concurrent_calls() -> None:
    release = asyncio.Event()

    async def wait_and_respond() -> object:
        await release.wait()
        return response()

    client = FakeClient(wait_and_respond, wait_and_respond)
    provider = DeepSeekProvider(settings(), client=client)

    first = asyncio.create_task(
        provider.invoke(request(ModelRole.USER), model="configured-model")
    )
    second = asyncio.create_task(
        provider.invoke(request(ModelRole.ASSISTANT), model="configured-model")
    )
    await asyncio.sleep(0)
    release.set()
    results = await asyncio.gather(first, second)

    assert [item.content for item in results] == ["hello", "hello"]
    assert len(client.responses.calls) == 2


def test_runtime_factory_configures_cheap_and_strong_routes() -> None:
    configured = settings(cheap_model="cheap-custom", strong_model="strong-custom")
    provider = DeepSeekProvider(configured, client=FakeClient())

    gateway = build_deepseek_gateway(configured, provider=provider)

    assert gateway.routes[ModelProfile.CHEAP].model == "cheap-custom"
    assert gateway.routes[ModelProfile.STRONG].model == "strong-custom"
    assert gateway.providers == {"deepseek": provider}
