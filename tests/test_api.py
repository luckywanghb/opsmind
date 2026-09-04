"""Developer tests for the public HTTP runtime boundary."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from uuid import UUID

import httpx
import pytest
from fastapi.testclient import TestClient

from opsmind.agent.errors import AgentInputError
from opsmind.agent.schemas import ActionDecisionOutput, RequestUnderstandingOutput
from opsmind.api.app import create_app
from opsmind.api.composition import RuntimeConfigurationError, build_runtime
from opsmind.api.runtime import AgentRunResult, OpsAgentRuntime
from opsmind.api.schemas import MAX_MESSAGE_LENGTH, MAX_THREAD_ID_LENGTH
from opsmind.api.settings import RuntimeSettings
from opsmind.models import (
    MockModelProvider,
    ModelGateway,
    ModelInvocationError,
    ModelProfile,
    ModelRoute,
    ModelStructuredOutputError,
    ModelTask,
)
from opsmind.state import (
    AgentAction,
    OpsAgentState,
    PrimaryIntent,
    RequestType,
    RiskSignal,
)


def _understanding() -> RequestUnderstandingOutput:
    return RequestUnderstandingOutput(
        primary_intent=PrimaryIntent.WORKFLOW_ISSUE,
        request_type=RequestType.DIAGNOSE,
        symptom="Work order is waiting for approval",
        entities={"work_order": "WO-42"},
        risk_signal=RiskSignal.NONE,
        uncertainty=None,
    )


def _decision() -> ActionDecisionOutput:
    return ActionDecisionOutput(
        action=AgentAction.SEARCH,
        goal="Inspect the current approval state",
        rationale="The current node is needed before explaining the delay",
    )


def _reply_decision() -> ActionDecisionOutput:
    return ActionDecisionOutput(
        action=AgentAction.REPLY,
        goal="已获得足够信息，可以回复",
        rationale="当前请求不需要额外工具查询",
    )


def _selection() -> dict[str, object]:
    return {
        "selected_tool": "work_order_query",
        "arguments": {"work_order_id": "WO-42"},
        "expected_resolution": "确认当前状态",
    }


def _review() -> dict[str, object]:
    return {
        "evidence_sufficient": True,
        "summary": "已确认当前状态。",
        "confirmed_facts": ["状态已确认"],
        "unresolved_questions": [],
        "recommended_action": "REPLY",
    }


def _runtime(
    responses: Iterable[object] | None = None,
) -> tuple[OpsAgentRuntime, MockModelProvider]:
    provider = MockModelProvider(
        structured_responses=list(
            responses or [_understanding(), _reply_decision()]
        ),
        responses=["已根据当前可确认信息完成回复。"],
    )
    gateway = ModelGateway(
        routes={
            ModelProfile.CHEAP: ModelRoute(
                profile=ModelProfile.CHEAP,
                provider="mock",
                model="mock-chat",
            )
        },
        providers={"mock": provider},
    )
    return OpsAgentRuntime(gateway), provider


def _client(
    responses: Iterable[object] | None = None,
    *,
    raise_server_exceptions: bool = True,
) -> tuple[TestClient, MockModelProvider]:
    runtime, provider = _runtime(responses)
    return (
        TestClient(
            create_app(runtime=runtime),
            raise_server_exceptions=raise_server_exceptions,
        ),
        provider,
    )


def test_health_is_provider_independent() -> None:
    client, provider = _client([ModelInvocationError("must not run")])

    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "opsmind"}
    assert response.headers["X-Request-ID"]
    assert provider.invocation_count == 0


def test_chat_runs_canonical_kernel_and_returns_safe_actual_trace() -> None:
    client, provider = _client(
        [
            _understanding(),
            _decision(),
            _selection(),
            _review(),
            _reply_decision(),
        ]
    )
    payload = {
        "message": "Why is WO-42 still waiting?",
        "thread_id": "plant-thread-7",
        "source_context": {"channel": "portal", "line": 3},
    }

    response = client.post("/api/v1/chat", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["request_id"] == response.headers["X-Request-ID"]
    assert body["thread_id"] == "plant-thread-7"
    assert body["status"] == "completed"
    assert body["final_status"] == "RESOLVED"
    assert body["final_reply"] == "已根据当前可确认信息完成回复。"
    assert body["understanding"] == _understanding().model_dump(mode="json")
    assert body["decision"] == _reply_decision().model_dump(mode="json")
    assert body["trace"] == [
        {
            "node": "understand_request",
            "task": "REQUEST_UNDERSTANDING",
            "profile": "CHEAP",
            "status": "completed",
            "summary": "WORKFLOW_ISSUE / DIAGNOSE",
        },
        {
            "node": "decide_action",
            "task": "ACTION_DECISION",
            "profile": "CHEAP",
            "status": "completed",
            "summary": "SEARCH: Inspect the current approval state",
        },
        {
            "node": "select_tool",
            "task": "TOOL_SELECTION",
            "profile": "CHEAP",
            "status": "completed",
            "summary": "work_order_query",
        },
        {
            "node": "execute_tool",
            "task": "TOOL_SELECTION",
            "profile": "HARNESS",
            "status": "completed",
            "summary": "work_order_query: not_found",
        },
        {
            "node": "review_tool_result",
            "task": "TOOL_RESULT_REVIEW",
            "profile": "CHEAP",
            "status": "completed",
            "summary": "已确认当前状态。",
        },
        {
            "node": "decide_action",
            "task": "ACTION_DECISION",
            "profile": "CHEAP",
            "status": "completed",
            "summary": "REPLY: 已获得足够信息，可以回复",
        },
        {
            "node": "generate_response",
            "task": "RESPONSE_GENERATION",
            "profile": "CHEAP",
            "status": "completed",
            "summary": "final response generated",
        },
    ]
    assert body["evidence"][0]["source"] == "work_order_query"
    assert provider.invocation_count == 6
    assert [call.task for call in provider.history] == [
        ModelTask.REQUEST_UNDERSTANDING,
        ModelTask.ACTION_DECISION,
        ModelTask.TOOL_SELECTION,
        ModelTask.TOOL_RESULT_REVIEW,
        ModelTask.ACTION_DECISION,
        ModelTask.RESPONSE_GENERATION,
    ]

    understanding_context = json.loads(provider.history[0].messages[1].content)
    assert understanding_context["current_query"] == payload["message"]
    assert understanding_context["original_query"] == payload["message"]
    assert understanding_context["source_context"] == payload["source_context"]


def test_chat_generates_thread_id_without_conflating_request_id() -> None:
    client, _ = _client()

    body = client.post("/api/v1/chat", json={"message": "Help"}).json()

    assert UUID(body["thread_id"])
    assert UUID(body["request_id"])
    assert body["thread_id"] != body["request_id"]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"message": None},
        {"message": ""},
        {"message": "  \n\t"},
        {"message": "x" * (MAX_MESSAGE_LENGTH + 1)},
        {"message": "ok", "thread_id": " "},
        {"message": "ok", "thread_id": "x" * (MAX_THREAD_ID_LENGTH + 1)},
        {"message": "ok", "source_context": []},
        {"message": "ok", "unexpected": True},
    ],
)
def test_chat_request_validation_uses_unified_422_error(payload: object) -> None:
    client, provider = _client()

    response = client.post("/api/v1/chat", json=payload)

    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "code": "REQUEST_VALIDATION_FAILED",
            "message": "Request validation failed",
            "request_id": response.headers["X-Request-ID"],
        }
    }
    assert provider.invocation_count == 0


def test_source_context_rejects_non_finite_json_number() -> None:
    client, provider = _client()

    response = client.post(
        "/api/v1/chat",
        content='{"message":"ok","source_context":{"value":NaN}}',
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "REQUEST_VALIDATION_FAILED"
    assert provider.invocation_count == 0


@pytest.mark.parametrize(
    ("failure", "code"),
    [
        (ModelInvocationError("provider secret"), "MODEL_INVOCATION_FAILED"),
        (
            ModelStructuredOutputError("raw provider output"),
            "MODEL_STRUCTURED_OUTPUT_INVALID",
        ),
    ],
)
def test_model_failures_are_secret_safe_502(failure: Exception, code: str) -> None:
    client, provider = _client([failure])

    response = client.post("/api/v1/chat", json={"message": "help"})

    assert response.status_code == 502
    body = response.json()
    assert body["error"]["code"] == code
    assert body["error"]["request_id"] == response.headers["X-Request-ID"]
    assert "secret" not in response.text
    assert "raw provider" not in response.text
    assert provider.invocation_count == 1


def test_invalid_structured_payload_is_502_and_stops_graph() -> None:
    client, provider = _client([{"not": "understanding"}, _decision()])

    response = client.post("/api/v1/chat", json={"message": "help"})

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "MODEL_STRUCTURED_OUTPUT_INVALID"
    assert provider.invocation_count == 1


class _FailingRuntime(OpsAgentRuntime):
    def __init__(self, failure: Exception) -> None:
        runtime, _ = _runtime()
        super().__init__(runtime.gateway)
        self._failure = failure

    async def run_with_trace(self, state: OpsAgentState) -> AgentRunResult:
        del state
        raise self._failure


def test_agent_input_error_is_400() -> None:
    app = create_app(runtime=_FailingRuntime(AgentInputError("raw input")))
    response = TestClient(app).post("/api/v1/chat", json={"message": "help"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_AGENT_INPUT"
    assert "raw input" not in response.text


def test_unexpected_error_is_secret_safe_500() -> None:
    app = create_app(runtime=_FailingRuntime(RuntimeError("private detail")))
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post("/api/v1/chat", json={"message": "help"})

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_SERVER_ERROR"
    assert response.json()["error"]["request_id"]
    assert "private detail" not in response.text


def test_logs_do_not_include_message_or_source_context(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, _ = _client()
    secret_message = "MESSAGE-MUST-NOT-BE-LOGGED"
    secret_context = "CONTEXT-MUST-NOT-BE-LOGGED"

    with caplog.at_level(logging.INFO, logger="opsmind.api"):
        response = client.post(
            "/api/v1/chat",
            json={
                "message": secret_message,
                "source_context": {"private": secret_context},
            },
        )

    assert response.status_code == 200
    assert secret_message not in caplog.text
    assert secret_context not in caplog.text
    assert response.json()["request_id"] in caplog.text
    assert response.json()["thread_id"] in caplog.text


def test_openapi_exposes_typed_chat_and_error_schemas() -> None:
    client, _ = _client()

    document = client.get("/openapi.json").json()

    chat = document["paths"]["/api/v1/chat"]["post"]
    assert chat["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ChatRequest"
    }
    assert chat["responses"]["200"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/ChatResponse"}
    assert chat["responses"]["502"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/ErrorResponse"}


def test_runtime_settings_default_to_mock_and_reject_unknown_provider() -> None:
    assert RuntimeSettings.from_env({}).model_provider == "mock"
    with pytest.raises(ValueError):
        RuntimeSettings.from_env({"OPSMIND_MODEL_PROVIDER": "silent-fallback"})


def test_deepseek_mode_missing_key_fails_without_mock_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    with pytest.raises(RuntimeConfigurationError) as captured:
        build_runtime(RuntimeSettings(model_provider="deepseek"))

    assert "DeepSeek" in str(captured.value)
    assert captured.value.__cause__ is not None


def test_deepseek_mode_builds_explicit_real_provider_routes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only-key")

    runtime = build_runtime(RuntimeSettings(model_provider="deepseek"))

    assert set(runtime.gateway.providers) == {"deepseek"}
    assert runtime.gateway.routes[ModelProfile.CHEAP].provider == "deepseek"
    assert runtime.gateway.routes[ModelProfile.STRONG].provider == "deepseek"


def test_default_mock_runtime_is_reusable() -> None:
    client = TestClient(create_app(settings=RuntimeSettings(model_provider="mock")))

    first = client.post("/api/v1/chat", json={"message": "one"})
    second = client.post("/api/v1/chat", json={"message": "two"})

    assert first.status_code == second.status_code == 200
    assert [step["node"] for step in first.json()["trace"]] == [
        "understand_request",
        "decide_action",
        "close_conversation",
    ]


@pytest.mark.asyncio
async def test_concurrent_requests_keep_request_thread_and_trace_isolated() -> None:
    app = create_app(settings=RuntimeSettings(model_provider="mock"))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        first, second = await __import__("asyncio").gather(
            client.post(
                "/api/v1/chat",
                json={"message": "first", "thread_id": "thread-first"},
            ),
            client.post(
                "/api/v1/chat",
                json={"message": "second", "thread_id": "thread-second"},
            ),
        )

    first_body = first.json()
    second_body = second.json()
    assert first_body["thread_id"] == "thread-first"
    assert second_body["thread_id"] == "thread-second"
    assert first_body["request_id"] != second_body["request_id"]
    assert len(first_body["trace"]) == len(second_body["trace"]) == 3
