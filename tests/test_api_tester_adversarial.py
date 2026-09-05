"""Independent adversarial tests for TASK-P1-005's HTTP/runtime boundary.

These tests intentionally build their own provider/runtime fixtures instead of
importing helpers from ``tests/test_api.py``.  They exercise the public HTTP
surface through the canonical LangGraph runtime and keep product code out of
the test-only change.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable
from typing import TypeVar
from uuid import UUID

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, ValidationError

from opsmind.agent.errors import AgentInputError
from opsmind.agent.schemas import ActionDecisionOutput, RequestUnderstandingOutput
from opsmind.api.app import create_app
from opsmind.api.composition import RuntimeConfigurationError, build_runtime
from opsmind.api.runtime import AgentRunResult, OpsAgentRuntime
from opsmind.api.schemas import MAX_MESSAGE_LENGTH, MAX_THREAD_ID_LENGTH, ChatRequest
from opsmind.api.settings import RuntimeSettings
from opsmind.models import (
    MockModelProvider,
    ModelGateway,
    ModelInvocationError,
    ModelProfile,
    ModelProvider,
    ModelRequest,
    ModelResponse,
    ModelRoute,
    ModelStructuredOutputError,
    ModelTask,
    StructuredModelResponse,
)
from opsmind.state import AgentAction, PrimaryIntent, RequestType, RiskSignal

T = TypeVar("T", bound=BaseModel)

_ERROR_MESSAGES = {
    "REQUEST_VALIDATION_FAILED": "Request validation failed",
    "INVALID_AGENT_INPUT": "Agent input is invalid",
    "MODEL_INVOCATION_FAILED": "Model invocation failed",
    "MODEL_STRUCTURED_OUTPUT_INVALID": "Model returned invalid structured output",
    "INTERNAL_SERVER_ERROR": "Internal server error",
}


def understanding(
    *,
    marker: str = "WO-42",
    symptom: str = "Work order is waiting for approval",
    entities: dict[str, object] | None = None,
) -> RequestUnderstandingOutput:
    return RequestUnderstandingOutput(
        primary_intent=PrimaryIntent.WORKFLOW_ISSUE,
        request_type=RequestType.DIAGNOSE,
        symptom=symptom,
        entities=entities if entities is not None else {"work_order": marker},
        risk_signal=RiskSignal.NONE,
        uncertainty=None,
    )


def decision(
    *,
    marker: str = "WO-42",
    action: AgentAction = AgentAction.SEARCH,
    goal: str | None = None,
    rationale: str = "The current node is needed before explaining the delay",
) -> ActionDecisionOutput:
    return ActionDecisionOutput(
        action=action,
        goal=goal or f"Inspect the current approval state for {marker}",
        rationale=rationale,
    )


def grounded_plan(action: str = "REPLY") -> dict[str, object]:
    intent = {
        "REPLY": "FACTS",
        "ASK_USER": "CLARIFICATION",
        "TRANSFER_HUMAN": "HANDOFF",
        "END_CONVERSATION": "CLOSE",
    }[action]
    return {
        "terminal_mode": action,
        "presentation_intent": intent,
        "evidence_references": [],
        "limitation": "NONE",
        "clarification_target": "GENERIC",
    }


def gateway_for(provider: ModelProvider) -> ModelGateway:
    return ModelGateway(
        routes={
            ModelProfile.CHEAP: ModelRoute(
                profile=ModelProfile.CHEAP,
                provider="test-provider",
                model="test-model",
            )
        },
        providers={"test-provider": provider},
    )


def runtime_for(
    responses: Iterable[object] | None = None,
) -> tuple[OpsAgentRuntime, MockModelProvider]:
    provider = MockModelProvider(
        structured_responses=(
            list(responses)
            if responses is not None
            else [
                understanding(),
                decision(action=AgentAction.REPLY),
                grounded_plan(),
            ]
        ),
        responses=[],
        provider_name="test-provider",
    )
    return OpsAgentRuntime(gateway_for(provider)), provider


def client_for(
    responses: Iterable[object] | None = None,
    *,
    raise_server_exceptions: bool = True,
) -> tuple[TestClient, MockModelProvider]:
    runtime, provider = runtime_for(responses)
    return (
        TestClient(
            create_app(runtime=runtime),
            raise_server_exceptions=raise_server_exceptions,
        ),
        provider,
    )


def assert_error(response: httpx.Response, status: int, code: str) -> None:
    assert response.status_code == status
    body = response.json()
    request_id = body["error"]["request_id"]
    assert body == {
        "error": {
            "code": code,
            "message": _ERROR_MESSAGES[code],
            "request_id": request_id,
        }
    }
    assert request_id
    assert response.headers.get("X-Request-ID") == request_id


class QueryAwareProvider:
    """Async provider that makes interleaving and state mix-ups observable."""

    def __init__(self) -> None:
        self.requests: list[ModelRequest] = []
        self._action_counts: dict[str, int] = {}

    @property
    def invocation_count(self) -> int:
        return len(self.requests)

    @staticmethod
    def _marker(request: ModelRequest) -> str:
        payload = json.loads(request.messages[-1].content)
        return str(payload["current_query"])

    async def invoke(
        self,
        request: ModelRequest,
        *,
        model: str,
    ) -> ModelResponse:
        self.requests.append(request.model_copy(deep=True))
        await asyncio.sleep(0)
        return ModelResponse(
            content="已根据当前可确认信息完成回复。",
            provider="test-provider",
            model=model,
        )

    async def invoke_structured(
        self,
        request: ModelRequest,
        response_model: type[T],
        *,
        model: str,
    ) -> StructuredModelResponse[T]:
        self.requests.append(request.model_copy(deep=True))
        marker = self._marker(request)
        await asyncio.sleep(0)
        if request.task is ModelTask.REQUEST_UNDERSTANDING:
            payload: BaseModel | dict[str, object] = understanding(
                marker=marker,
                symptom=f"symptom:{marker}",
                entities={"marker": marker},
            )
        elif request.task is ModelTask.ACTION_DECISION:
            count = self._action_counts.get(marker, 0)
            self._action_counts[marker] = count + 1
            payload = decision(
                marker=marker,
                action=AgentAction.SEARCH if count == 0 else AgentAction.REPLY,
                goal=f"goal:{marker}",
            )
        elif request.task is ModelTask.TOOL_SELECTION:
            payload = {
                "selected_tool": "work_order_query",
                "arguments": {"work_order_id": "WO-INTEGRATION"},
                "expected_resolution": "confirm status",
            }
        elif request.task is ModelTask.TOOL_RESULT_REVIEW:
            payload = {
                "evidence_sufficient": True,
                "summary": "reviewed read-only facts",
                "confirmed_facts": ["a typed result was reviewed"],
                "unresolved_questions": [],
                "recommended_action": "REPLY",
            }
        else:
            payload = grounded_plan()
        parsed = response_model.model_validate(
            payload.model_dump() if isinstance(payload, BaseModel) else payload
        )
        return StructuredModelResponse(
            parsed=parsed,
            response=ModelResponse(
                content="provider-payload-must-not-be-traced",
                provider="test-provider",
                model=model,
            ),
        )


def test_health_contract_has_service_and_does_not_invoke_provider() -> None:
    client, provider = client_for([ModelInvocationError("health must not call me")])

    response = client.get("/api/v1/health")

    assert response.status_code == 200
    # TASK-P1-005 section 9 requires both process status and service identity.
    assert response.json() == {"status": "ok", "service": "opsmind"}
    assert response.headers["X-Request-ID"]
    assert provider.invocation_count == 0


@pytest.mark.parametrize(
    "payload",
    [
        {},
        None,
        [],
        {"message": None},
        {"message": 123},
        {"message": ["help"]},
        {"message": ""},
        {"message": "\t\r\n\u00a0\u2003\u2028\u2029\u3000"},
        {"message": "x" * (MAX_MESSAGE_LENGTH + 1)},
        {"message": "ok", "thread_id": 123},
        {"message": "ok", "thread_id": []},
        {"message": "ok", "thread_id": ""},
        {"message": "ok", "thread_id": " "},
        {"message": "ok", "thread_id": "x" * (MAX_THREAD_ID_LENGTH + 1)},
        {"message": "ok", "source_context": []},
        {"message": "ok", "source_context": "not-an-object"},
        {"message": "ok", "unexpected": True},
    ],
)
def test_malformed_request_never_reaches_runtime(payload: object) -> None:
    client, provider = client_for()

    response = client.post("/api/v1/chat", json=payload)

    assert_error(response, 422, "REQUEST_VALIDATION_FAILED")
    assert provider.invocation_count == 0


@pytest.mark.parametrize("raw_body", [b"", b"{", b'{"message":"ok",}', b"not-json"])
def test_invalid_json_uses_sanitized_validation_envelope(raw_body: bytes) -> None:
    client, provider = client_for()

    response = client.post(
        "/api/v1/chat",
        content=raw_body,
        headers={"Content-Type": "application/json"},
    )

    assert_error(response, 422, "REQUEST_VALIDATION_FAILED")
    assert provider.invocation_count == 0


def test_message_exact_limit_is_accepted() -> None:
    client, provider = client_for()

    response = client.post(
        "/api/v1/chat",
        json={"message": "x" * MAX_MESSAGE_LENGTH},
    )

    assert response.status_code == 200
    assert provider.invocation_count == 3


def test_zero_width_space_only_message_is_not_treated_as_content() -> None:
    client, provider = client_for()

    response = client.post("/api/v1/chat", json={"message": "\u200b"})

    assert_error(response, 422, "REQUEST_VALIDATION_FAILED")
    assert provider.invocation_count == 0


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
def test_source_context_rejects_nested_non_finite_json(token: str) -> None:
    client, provider = client_for()
    raw_body = (
        '{"message":"ok","source_context":'
        '{"nested":[{"value":' + token + '}]}}'
    )

    response = client.post(
        "/api/v1/chat",
        content=raw_body,
        headers={"Content-Type": "application/json"},
    )

    assert_error(response, 422, "REQUEST_VALIDATION_FAILED")
    assert provider.invocation_count == 0


def test_source_context_preserves_only_finite_json_values_in_state_projection() -> None:
    client, provider = client_for()
    context = {
        "channel": "web",
        "enabled": True,
        "count": 3,
        "ratio": 0.25,
        "empty": None,
        "nested": {"items": ["a", False, 0]},
    }

    response = client.post(
        "/api/v1/chat",
        json={"message": "help", "source_context": context},
    )

    assert response.status_code == 200
    first_context = json.loads(provider.history[0].messages[-1].content)
    assert first_context["source_context"] == context


def test_source_context_rejects_arbitrary_python_objects_at_contract_boundary() -> None:
    with pytest.raises(ValidationError):
        ChatRequest.model_validate(
            {"message": "help", "source_context": {"object": object()}}
        )


def test_thread_and_request_ids_are_distinct_and_correlated() -> None:
    client, _ = client_for()
    supplied_thread = "租户/线程-7"

    response = client.post(
        "/api/v1/chat",
        json={"message": "help", "thread_id": supplied_thread},
    )
    body = response.json()

    assert response.status_code == 200
    assert body["thread_id"] == supplied_thread
    assert body["request_id"] == response.headers["X-Request-ID"]
    UUID(body["request_id"])
    assert body["request_id"] != body["thread_id"]


def test_omitted_thread_id_is_generated_without_reusing_request_id() -> None:
    client, _ = client_for()

    body = client.post("/api/v1/chat", json={"message": "help"}).json()

    UUID(body["thread_id"])
    UUID(body["request_id"])
    assert body["thread_id"] != body["request_id"]


def test_http_to_langgraph_to_gateway_integration_maps_state_and_trace() -> None:
    provider = QueryAwareProvider()
    client = TestClient(create_app(runtime=OpsAgentRuntime(gateway_for(provider))))
    payload = {
        "message": "WO-INTEGRATION still waiting",
        "thread_id": "integration-thread",
        "source_context": {"channel": "web", "page": "work-order"},
    }

    response = client.post("/api/v1/chat", json=payload)
    body = response.json()

    assert response.status_code == 200
    assert body["thread_id"] == payload["thread_id"]
    assert body["understanding"]["entities"] == {"marker": payload["message"]}
    assert body["decision"]["goal"] == f"goal:{payload['message']}"
    assert [request.task for request in provider.requests] == [
        ModelTask.REQUEST_UNDERSTANDING,
        ModelTask.ACTION_DECISION,
        ModelTask.TOOL_SELECTION,
        ModelTask.TOOL_RESULT_REVIEW,
        ModelTask.ACTION_DECISION,
        ModelTask.RESPONSE_GENERATION,
    ]
    assert all(request.profile is ModelProfile.CHEAP for request in provider.requests)
    assert [request.metadata["node"] for request in provider.requests] == [
        "understand_request",
        "decide_action",
        "select_tool",
        "review_tool_result",
        "decide_action",
        "generate_response",
    ]
    first_context = json.loads(provider.requests[0].messages[-1].content)
    second_context = json.loads(provider.requests[1].messages[-1].content)
    assert first_context["current_query"] == payload["message"]
    assert first_context["original_query"] == payload["message"]
    assert first_context["source_context"] == payload["source_context"]
    assert second_context["understanding"]["entities"] == {
        "marker": payload["message"]
    }
    assert [step["node"] for step in body["trace"]] == [
        "understand_request",
        "decide_action",
        "select_tool",
        "execute_tool",
        "review_tool_result",
        "decide_action",
        "generate_response",
    ]
    assert [step["task"] for step in body["trace"]] == [
        "REQUEST_UNDERSTANDING",
        "ACTION_DECISION",
        "TOOL_SELECTION",
        "TOOL_SELECTION",
        "TOOL_RESULT_REVIEW",
        "ACTION_DECISION",
        "RESPONSE_GENERATION",
    ]
    assert [step["profile"] for step in body["trace"]] == [
        "CHEAP",
        "CHEAP",
        "CHEAP",
        "HARNESS",
        "CHEAP",
        "CHEAP",
        "CHEAP",
    ]
    assert all(step["status"] == "completed" for step in body["trace"])


@pytest.mark.asyncio
async def test_concurrent_requests_keep_trace_and_state_isolated() -> None:
    provider = QueryAwareProvider()
    app = create_app(runtime=OpsAgentRuntime(gateway_for(provider)))
    transport = httpx.ASGITransport(app=app)
    messages = [f"request-{index}" for index in range(10)]
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        responses = await asyncio.gather(
            *(
                client.post(
                    "/api/v1/chat",
                    json={
                        "message": message,
                        "thread_id": "same-thread",
                    },
                )
                for message in messages
            )
        )

    assert all(response.status_code == 200 for response in responses)
    bodies = [response.json() for response in responses]
    assert len({body["request_id"] for body in bodies}) == len(messages)
    for message, body in zip(messages, bodies, strict=True):
        assert body["thread_id"] == "same-thread"
        assert body["decision"]["goal"] == f"goal:{message}"
        assert body["trace"][1]["summary"] == "SEARCH"


def test_trace_exposes_only_safe_facts_not_raw_provider_payload_or_cot() -> None:
    raw_provider_secret = "RAW-PROVIDER-SECRET-DO-NOT-TRACE"
    hidden_cot = "HIDDEN-COT-DO-NOT-TRACE"
    first = StructuredModelResponse(
        parsed=understanding(),
        response=ModelResponse(
            content=raw_provider_secret,
            provider="test-provider",
            model="test-model",
        ),
    )
    second = decision(action=AgentAction.REPLY, rationale=hidden_cot)
    client, _ = client_for([first, second, grounded_plan()])

    response = client.post(
        "/api/v1/chat",
        json={
            "message": "user-message-must-not-appear-in-trace",
            "source_context": {"private": "source-context-must-not-appear"},
        },
    )

    assert response.status_code == 200
    trace_text = json.dumps(response.json()["trace"])
    assert raw_provider_secret not in trace_text
    assert hidden_cot not in trace_text
    assert "user-message-must-not-appear-in-trace" not in trace_text
    assert "source-context-must-not-appear" not in trace_text
    assert all(set(step) == {"node", "task", "profile", "status", "summary"}
               for step in response.json()["trace"])


def test_first_model_invocation_failure_short_circuits_second_node() -> None:
    client, provider = client_for(
        [ModelInvocationError("Authorization: Bearer provider-secret"), decision()]
    )

    response = client.post("/api/v1/chat", json={"message": "help"})

    assert_error(response, 502, "MODEL_INVOCATION_FAILED")
    assert provider.invocation_count == 1
    assert [call.task for call in provider.history] == [
        ModelTask.REQUEST_UNDERSTANDING
    ]
    assert "provider-secret" not in response.text
    assert "Authorization" not in response.text


def test_second_model_invocation_failure_is_attempted_but_sanitized() -> None:
    client, provider = client_for(
        [understanding(), ModelInvocationError("provider-private-detail")]
    )

    response = client.post("/api/v1/chat", json={"message": "help"})

    assert_error(response, 502, "MODEL_INVOCATION_FAILED")
    assert provider.invocation_count == 2
    assert [call.task for call in provider.history] == [
        ModelTask.REQUEST_UNDERSTANDING,
        ModelTask.ACTION_DECISION,
    ]
    assert "provider-private-detail" not in response.text


def test_second_structured_output_failure_does_not_return_partial_trace() -> None:
    client, provider = client_for(
        [understanding(), ModelStructuredOutputError("raw malformed provider JSON")]
    )

    response = client.post("/api/v1/chat", json={"message": "help"})

    assert_error(response, 502, "MODEL_STRUCTURED_OUTPUT_INVALID")
    assert provider.invocation_count == 2
    assert "raw malformed provider JSON" not in response.text


class RaisingRuntime(OpsAgentRuntime):
    def __init__(self, failure: Exception) -> None:
        runtime, _ = runtime_for()
        super().__init__(runtime.gateway)
        self.failure = failure

    async def run_with_trace(self, state: object) -> AgentRunResult:  # type: ignore[override]
        del state
        raise self.failure


def test_agent_input_error_maps_to_400_without_internal_detail() -> None:
    app = create_app(runtime=RaisingRuntime(AgentInputError("private input detail")))
    response = TestClient(app).post("/api/v1/chat", json={"message": "help"})

    assert_error(response, 400, "INVALID_AGENT_INPUT")
    assert "private input detail" not in response.text


def test_unexpected_runtime_error_maps_to_500_without_traceback_or_path() -> None:
    app = create_app(
        runtime=RaisingRuntime(
            RuntimeError("/private/opsmind traceback and runtime-secret")
        )
    )
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post("/api/v1/chat", json={"message": "help"})

    assert_error(response, 500, "INTERNAL_SERVER_ERROR")
    assert "/private/opsmind" not in response.text
    assert "traceback" not in response.text.lower()
    assert "runtime-secret" not in response.text


def test_runtime_configuration_is_explicit_and_never_silently_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only-key")
    monkeypatch.setenv("OPSMIND_CHEAP_MODEL", "cheap-configured")
    monkeypatch.setenv("OPSMIND_STRONG_MODEL", "strong-configured")

    runtime = build_runtime(RuntimeSettings(model_provider="deepseek"))

    assert set(runtime.gateway.providers) == {"deepseek"}
    assert runtime.gateway.routes[ModelProfile.CHEAP].provider == "deepseek"
    assert runtime.gateway.routes[ModelProfile.CHEAP].model == "cheap-configured"
    assert runtime.gateway.routes[ModelProfile.STRONG].provider == "deepseek"
    assert runtime.gateway.routes[ModelProfile.STRONG].model == "strong-configured"


def test_deepseek_without_key_fails_at_configuration_not_as_mock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    with pytest.raises(RuntimeConfigurationError) as captured:
        build_runtime(RuntimeSettings(model_provider="deepseek"))

    assert "DeepSeek" in str(captured.value)
    assert captured.value.__cause__ is not None


def test_unknown_runtime_provider_is_rejected() -> None:
    with pytest.raises(ValidationError):
        RuntimeSettings.from_env({"OPSMIND_MODEL_PROVIDER": "mock-or-deepseek"})


def test_openapi_lists_versioned_routes_and_typed_public_schemas() -> None:
    client, _ = client_for()

    document = client.get("/openapi.json").json()
    schemas = document["components"]["schemas"]

    assert set(document["paths"]) >= {"/api/v1/health", "/api/v1/chat"}
    assert "post" in document["paths"]["/api/v1/chat"]
    assert "get" in document["paths"]["/api/v1/health"]
    for schema_name in (
        "ChatRequest",
        "ChatResponse",
        "AgentTraceStep",
        "ErrorResponse",
    ):
        assert schema_name in schemas
    chat_request = schemas["ChatRequest"]
    assert chat_request["required"] == ["message"]
    assert chat_request["properties"]["message"]["maxLength"] == MAX_MESSAGE_LENGTH
    thread_schema = chat_request["properties"]["thread_id"]
    thread_variants = thread_schema.get("anyOf", [thread_schema])
    assert any(
        variant.get("maxLength") == MAX_THREAD_ID_LENGTH
        for variant in thread_variants
    )
    assert document["paths"]["/api/v1/chat"]["post"]["responses"]["502"][
        "content"
    ]["application/json"]["schema"] == {"$ref": "#/components/schemas/ErrorResponse"}
