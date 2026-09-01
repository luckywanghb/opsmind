"""Independent adversarial coverage for the P1-004 DeepSeek adapter.

These tests intentionally use a private transport fixture instead of the
developer-authored DeepSeek tests.  They exercise the provider boundary only;
no test invokes a real model API.
"""

from __future__ import annotations

import asyncio
import json
import math
import traceback
from collections import deque
from enum import StrEnum
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

import opsmind.models.providers.deepseek as deepseek_module
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


class _Decision(StrEnum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"


class _Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: _Decision
    rationale: str


class _FirstAnswer(BaseModel):
    first: int


class _SecondAnswer(BaseModel):
    second: str


class _ScoreAnswer(BaseModel):
    score: float


class _Transport:
    """Small async Responses API double with deterministic queued results."""

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


class _Client:
    def __init__(self, *results: object) -> None:
        self.responses = _Transport(*results)


class _Clock:
    def __init__(self, *values: float) -> None:
        self.values = deque(values)

    def __call__(self) -> float:
        return self.values.popleft()


def _settings(**overrides: object) -> DeepSeekSettings:
    return DeepSeekSettings.model_validate(
        {"api_key": "tester-only-secret", **overrides}
    )


def _request(*roles: ModelRole, metadata: dict[str, Any] | None = None) -> ModelRequest:
    return ModelRequest(
        task=ModelTask.REQUEST_UNDERSTANDING,
        profile=ModelProfile.CHEAP,
        messages=[
            ModelMessage(role=role, content=f"message-{index}")
            for index, role in enumerate(roles)
        ],
        metadata=metadata or {"node": "tester", "secret_marker": "must-not-send"},
    )


def _response(
    content: str = "ok",
    *,
    model: str = "tester-model",
    status: object = "completed",
    finish_reason: object = None,
    usage: object = None,
    response_id: object = "response-id",
) -> dict[str, object]:
    result: dict[str, object] = {
        "output_text": content,
        "model": model,
        "status": status,
        "id": response_id,
    }
    if finish_reason is not None:
        result["finish_reason"] = finish_reason
    if usage is not None:
        result["usage"] = usage
    return result


@pytest.mark.asyncio
async def test_roles_are_mapped_and_request_metadata_stays_provider_neutral() -> None:
    client = _Client(_response())
    provider = DeepSeekProvider(_settings(), client=client)

    await provider.invoke(
        _request(ModelRole.SYSTEM, ModelRole.USER, ModelRole.ASSISTANT),
        model="tester-model",
    )

    call = client.responses.calls[0]
    assert call["model"] == "tester-model"
    assert call["input"] == [
        {"type": "message", "role": "system", "content": "message-0"},
        {"type": "message", "role": "user", "content": "message-1"},
        {"type": "message", "role": "assistant", "content": "message-2"},
    ]
    assert "metadata" not in call


@pytest.mark.asyncio
async def test_finish_reason_field_is_preserved_when_status_is_absent() -> None:
    client = _Client(
        {
            "output_text": "done",
            "model": "tester-model",
            "finish_reason": "stop",
            "id": "response-id",
        }
    )
    provider = DeepSeekProvider(_settings(), client=client)

    result = await provider.invoke(_request(ModelRole.USER), model="tester-model")

    assert result.finish_reason == "stop"
    assert result.request_id is None


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_usage", ["not-an-object", [], 17, object(), {"other": 1}])
async def test_malformed_usage_shape_is_not_silently_treated_as_missing(
    bad_usage: object,
) -> None:
    provider = DeepSeekProvider(
        _settings(),
        client=_Client(_response(usage=bad_usage)),
    )

    with pytest.raises(ModelInvocationError):
        await provider.invoke(_request(ModelRole.USER), model="tester-model")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_usage",
    [
        {"input_tokens": -1},
        {"output_tokens": -1},
        {"total_tokens": -1},
        {"input_tokens": 1.5},
        {"output_tokens": "4"},
    ],
)
async def test_negative_or_wrongly_typed_usage_is_an_invocation_error(
    bad_usage: dict[str, object],
) -> None:
    provider = DeepSeekProvider(
        _settings(),
        client=_Client(_response(usage=bad_usage)),
    )

    with pytest.raises(ModelInvocationError):
        await provider.invoke(_request(ModelRole.USER), model="tester-model")


@pytest.mark.asyncio
@pytest.mark.parametrize("clock_values", [(1.0, math.nan), (1.0, 0.5)])
async def test_nan_or_negative_latency_is_rejected_for_text_and_structured(
    clock_values: tuple[float, float],
) -> None:
    text_provider = DeepSeekProvider(
        _settings(),
        client=_Client(_response()),
        clock=_Clock(*clock_values),
    )
    with pytest.raises(ModelInvocationError):
        await text_provider.invoke(_request(ModelRole.USER), model="tester-model")

    structured_provider = DeepSeekProvider(
        _settings(),
        client=_Client(
            _response(json.dumps({"decision": "ACCEPT", "rationale": "ok"}))
        ),
        clock=_Clock(*clock_values),
    )
    with pytest.raises(ModelInvocationError):
        await structured_provider.invoke_structured(
            _request(ModelRole.USER), _Answer, model="tester-model"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        TimeoutError("deadline exceeded"),
        RuntimeError("HTTP 401 unauthorized"),
        RuntimeError("HTTP 429 rate limited"),
        RuntimeError("HTTP 500 server failure"),
    ],
)
async def test_transport_failures_map_to_invocation_error_for_both_paths(
    failure: Exception,
) -> None:
    text_provider = DeepSeekProvider(_settings(), client=_Client(failure))
    with pytest.raises(ModelInvocationError) as text_error:
        await text_provider.invoke(_request(ModelRole.USER), model="tester-model")
    assert text_error.value.__cause__ is None
    assert text_error.value.__context__ is None

    structured_provider = DeepSeekProvider(
        _settings(),
        client=_Client(failure),
    )
    with pytest.raises(ModelInvocationError) as structured_error:
        await structured_provider.invoke_structured(
            _request(ModelRole.USER), _Answer, model="tester-model"
        )
    assert structured_error.value.__cause__ is None
    assert structured_error.value.__context__ is None


@pytest.mark.asyncio
async def test_transport_error_message_does_not_copy_a_secret_into_outer_error(
) -> None:
    secret = "tester-secret-that-must-not-leak"
    failure = RuntimeError(f"request Authorization Bearer {secret} failed")
    provider = DeepSeekProvider(
        _settings(api_key=secret),
        client=_Client(failure),
    )

    with pytest.raises(ModelInvocationError) as error:
        await provider.invoke(_request(ModelRole.USER), model="tester-model")

    rendered = "".join(traceback.format_exception(error.value))
    assert secret not in str(error.value)
    assert secret not in repr(error.value)
    assert secret not in rendered
    assert error.value.__cause__ is None
    assert error.value.__context__ is None


@pytest.mark.asyncio
async def test_cancellation_propagates_for_structured_call() -> None:
    provider = DeepSeekProvider(
        _settings(),
        client=_Client(asyncio.CancelledError()),
    )

    with pytest.raises(asyncio.CancelledError):
        await provider.invoke_structured(
            _request(ModelRole.USER), _Answer, model="tester-model"
        )


@pytest.mark.asyncio
async def test_cancelling_an_inflight_transport_task_is_not_wrapped() -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    class BlockingTransport:
        async def create(self, **kwargs: object) -> object:
            started.set()
            await release.wait()
            return _response()

    transport = BlockingTransport()
    client = type("Client", (), {"responses": transport})()
    provider = DeepSeekProvider(_settings(), client=client)
    task = asyncio.create_task(
        provider.invoke(_request(ModelRole.USER), model="tester-model")
    )
    await started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_response",
    [
        {},
        {"output_text": 123, "model": "tester-model"},
        {"output": "not-a-list", "model": "tester-model"},
        {"output": [], "model": "tester-model"},
    ],
)
async def test_empty_or_malformed_text_response_is_not_accepted(
    bad_response: dict[str, object],
) -> None:
    provider = DeepSeekProvider(_settings(), client=_Client(bad_response))

    with pytest.raises(ModelInvocationError):
        await provider.invoke(_request(ModelRole.USER), model="tester-model")


@pytest.mark.asyncio
async def test_provider_model_mismatch_is_rejected_for_text_and_structured() -> None:
    text_provider = DeepSeekProvider(
        _settings(),
        client=_Client(_response(model="actual-model")),
    )
    with pytest.raises(ModelInvocationError):
        await text_provider.invoke(_request(ModelRole.USER), model="requested-model")

    structured_provider = DeepSeekProvider(
        _settings(),
        client=_Client(
            _response(
                json.dumps({"decision": "ACCEPT", "rationale": "ok"}),
                model="actual-model",
            )
        ),
    )
    with pytest.raises(ModelStructuredOutputError):
        await structured_provider.invoke_structured(
            _request(ModelRole.USER), _Answer, model="requested-model"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_content",
    [
        "",
        "{\"decision\":\"ACCEPT\"",
        "{\"decision\":\"OTHER\",\"rationale\":\"x\"}",
        "{\"decision\":\"ACCEPT\",\"rationale\":\"x\",\"extra\":true}",
        "not-json",
    ],
)
async def test_invalid_truncated_enum_or_schema_json_is_structured_error(
    bad_content: str,
) -> None:
    provider = DeepSeekProvider(
        _settings(),
        client=_Client(_response(bad_content)),
    )

    with pytest.raises(ModelStructuredOutputError):
        await provider.invoke_structured(
            _request(ModelRole.USER), _Answer, model="tester-model"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("nonstandard_json", ["NaN", "Infinity", "-Infinity"])
async def test_nonstandard_nonfinite_json_is_a_structured_error(
    nonstandard_json: str,
) -> None:
    provider = DeepSeekProvider(
        _settings(),
        client=_Client(_response(f'{{"score": {nonstandard_json}}}')),
    )

    with pytest.raises(ModelStructuredOutputError):
        await provider.invoke_structured(
            _request(ModelRole.USER), _ScoreAnswer, model="tester-model"
        )


@pytest.mark.asyncio
async def test_structured_schema_and_response_models_do_not_bleed_across_calls(
) -> None:
    client = _Client(
        _response(json.dumps({"first": 7}), model="first-model"),
        _response(json.dumps({"second": "ok"}), model="second-model"),
    )
    provider = DeepSeekProvider(_settings(), client=client)

    first, second = await asyncio.gather(
        provider.invoke_structured(
            _request(ModelRole.USER), _FirstAnswer, model="first-model"
        ),
        provider.invoke_structured(
            _request(ModelRole.USER), _SecondAnswer, model="second-model"
        ),
    )

    assert first.parsed == _FirstAnswer(first=7)
    assert second.parsed == _SecondAnswer(second="ok")
    schemas = [
        call["text"]["format"]["schema"]  # type: ignore[index]
        for call in client.responses.calls
    ]
    assert "first" in schemas[0]["properties"]  # type: ignore[index]
    assert "second" in schemas[1]["properties"]  # type: ignore[index]
    assert "second" not in schemas[0]["properties"]  # type: ignore[index]
    assert "first" not in schemas[1]["properties"]  # type: ignore[index]


@pytest.mark.asyncio
async def test_shared_provider_is_safe_for_concurrent_calls() -> None:
    release = asyncio.Event()

    class ConcurrentTransport:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        async def create(self, **kwargs: object) -> object:
            self.calls.append(kwargs)
            await release.wait()
            model = kwargs["model"]
            return _response(str(model), model=str(model))

    transport = ConcurrentTransport()
    client = type("Client", (), {"responses": transport})()
    provider = DeepSeekProvider(_settings(), client=client)
    first_task = asyncio.create_task(
        provider.invoke(_request(ModelRole.USER), model="first-model")
    )
    second_task = asyncio.create_task(
        provider.invoke(_request(ModelRole.ASSISTANT), model="second-model")
    )
    await asyncio.sleep(0)
    release.set()
    first, second = await asyncio.gather(first_task, second_task)

    assert {first.content, second.content} == {"first-model", "second-model"}
    assert len(transport.calls) == 2


def test_settings_and_provider_repr_redact_api_key() -> None:
    secret = "tester-secret-that-must-never-appear"
    configured = _settings(api_key=secret)
    provider = DeepSeekProvider(configured, client=_Client())

    assert secret not in str(configured)
    assert secret not in repr(configured)
    assert secret not in repr(configured.model_dump())
    assert secret not in configured.model_dump_json()
    assert secret not in repr(provider)


@pytest.mark.asyncio
async def test_default_async_client_receives_validated_transport_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class CapturingClient:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)
            self.responses = _Transport(_response())

    monkeypatch.setattr(deepseek_module, "AsyncOpenAI", CapturingClient)
    provider = DeepSeekProvider(
        _settings(base_url="https://example.invalid", timeout_seconds=2.5)
    )

    await provider.invoke(_request(ModelRole.USER), model="tester-model")

    assert captured == {
        "api_key": "tester-only-secret",
        "base_url": "https://example.invalid",
        "timeout": 2.5,
    }


@pytest.mark.parametrize("timeout", [True, False, math.inf, math.nan, 0, -1])
def test_timeout_must_be_a_finite_positive_number(timeout: object) -> None:
    with pytest.raises(ValidationError):
        DeepSeekSettings.model_validate(
            {"api_key": "tester-only-secret", "timeout_seconds": timeout}
        )


def test_runtime_routes_keep_cheap_and_strong_models_configurable() -> None:
    settings = _settings(cheap_model="cheap-test", strong_model="strong-test")
    provider = DeepSeekProvider(settings, client=_Client())
    gateway = build_deepseek_gateway(settings, provider=provider)

    assert gateway.routes[ModelProfile.CHEAP].provider == "deepseek"
    assert gateway.routes[ModelProfile.CHEAP].model == "cheap-test"
    assert gateway.routes[ModelProfile.STRONG].provider == "deepseek"
    assert gateway.routes[ModelProfile.STRONG].model == "strong-test"
    assert gateway.providers["deepseek"] is provider


class _BrokenSchema(BaseModel):
    value: str

    @classmethod
    def model_json_schema(cls, *args: Any, **kwargs: Any) -> dict[str, object]:
        raise RuntimeError("schema generation failed")


@pytest.mark.asyncio
async def test_schema_generation_failure_is_a_structured_output_error() -> None:
    provider = DeepSeekProvider(_settings(), client=_Client())

    with pytest.raises(ModelStructuredOutputError):
        await provider.invoke_structured(
            _request(ModelRole.USER), _BrokenSchema, model="tester-model"
        )
