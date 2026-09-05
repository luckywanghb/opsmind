"""Independent regression checks for the escalation-remediation boundary.

These checks focus on the new schema, diagnostics, and public trace claims.
They use only deterministic provider doubles and never call a live model.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TypeAlias

import pytest
from fastapi.testclient import TestClient

from opsmind import (
    ActionDecisionOutput,
    AgentTraceEvent,
    MockModelProvider,
    ModelGateway,
    ModelInvocationError,
    ModelProfile,
    ModelRoute,
    ModelStructuredOutputError,
    ModelTask,
    RequestUnderstandingOutput,
)
from opsmind.api.app import create_app
from opsmind.api.runtime import OpsAgentRuntime

ErrorFactory: TypeAlias = Callable[
    [str], ModelInvocationError | ModelStructuredOutputError
]


def _gateway(provider: MockModelProvider) -> ModelGateway:
    return ModelGateway(
        routes={
            ModelProfile.CHEAP: ModelRoute(
                profile=ModelProfile.CHEAP,
                provider="retest",
                model="retest-cheap",
            )
        },
        providers={"retest": provider},
    )


def _understanding() -> dict[str, object]:
    return {
        "primary_intent": "WORKFLOW_ISSUE",
        "request_type": "DIAGNOSE",
        "symptom": "查询工单状态",
        "entities": {"work_order_id": "WO20260001"},
        "risk_signal": "NONE",
        "uncertainty": None,
    }


def _decision() -> dict[str, object]:
    return {
        "action": "SEARCH",
        "goal": "确认当前事实",
        "rationale": "需要读取状态",
    }


def _selection() -> dict[str, object]:
    return {
        "selected_tool": "work_order_query",
        "arguments": {"work_order_id": "WO20260001"},
        "expected_resolution": "确认当前状态",
    }


def _queue_for_node(
    failed_node: str,
    failure: ModelInvocationError | ModelStructuredOutputError,
) -> list[object]:
    prefix: dict[str, list[object]] = {
        "understand_request": [],
        "decide_action": [_understanding()],
        "select_tool": [_understanding(), _decision()],
        "review_tool_result": [
            _understanding(),
            _decision(),
            _selection(),
        ],
    }
    return [*prefix[failed_node], failure]


def _structured_failure(secret: str) -> ModelStructuredOutputError:
    return ModelStructuredOutputError(secret)


def _invocation_failure(secret: str) -> ModelInvocationError:
    return ModelInvocationError(secret)


_NODE_CASES = [
    ("understand_request", RequestUnderstandingOutput.__name__),
    ("decide_action", ActionDecisionOutput.__name__),
    ("select_tool", "ToolSelectionOutput"),
    ("review_tool_result", "ToolResultReviewOutput"),
]


@pytest.mark.parametrize(
    ("failed_node", "expected_schema"),
    _NODE_CASES,
)
@pytest.mark.parametrize(
    ("factory", "category", "error_label"),
    [
        (_structured_failure, "schema_mismatch", "structured"),
        (_invocation_failure, "invocation_failed", "invocation"),
    ],
)
def test_each_structured_node_api_failure_has_only_allowlisted_diagnostic(
    caplog: pytest.LogCaptureFixture,
    failed_node: str,
    expected_schema: str,
    factory: ErrorFactory,
    category: str,
    error_label: str,
) -> None:
    private_error = f"PRIVATE-{error_label}-PROMPT-PAYLOAD-123"
    private_query = "PRIVATE-USER-CONTEXT-456"
    provider = MockModelProvider(
        structured_responses=_queue_for_node(failed_node, factory(private_error)),
        provider_name="retest",
    )
    client = TestClient(
        create_app(runtime=OpsAgentRuntime(_gateway(provider))),
        raise_server_exceptions=False,
    )

    with caplog.at_level(logging.WARNING, logger="opsmind.api"):
        response = client.post(
            "/api/v1/chat",
            json={"message": f"查询状态 {private_query}"},
        )

    assert response.status_code == 502
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "request_id"}
    assert body["error"]["code"] in {
        "MODEL_STRUCTURED_OUTPUT_INVALID",
        "MODEL_INVOCATION_FAILED",
    }
    assert private_error not in response.text
    assert private_query not in response.text

    records = [
        record
        for record in caplog.records
        if record.name == "opsmind.api"
        and record.getMessage().startswith("structured_node_failure ")
    ]
    assert len(records) == 1
    message = records[0].getMessage()
    assert message == (
        "structured_node_failure "
        f"request_id={body['error']['request_id']} "
        f"node={failed_node} expected_schema_name={expected_schema} "
        f"logical_profile=CHEAP category={category}"
    )
    assert private_error not in message
    assert private_query not in message
    assert set(part.split("=", 1)[0] for part in message.split()[1:]) == {
        "request_id",
        "node",
        "expected_schema_name",
        "logical_profile",
        "category",
    }


def test_unallowlisted_error_category_is_normalized_before_logging() -> None:
    private_category = "PRIVATE-CATEGORY-DO-NOT-LOG"
    failure = ModelStructuredOutputError("PRIVATE-ERROR-DETAIL")
    failure.category = private_category  # type: ignore[attr-defined]
    provider = MockModelProvider(
        structured_responses=[failure],
        provider_name="retest",
    )
    client = TestClient(
        create_app(runtime=OpsAgentRuntime(_gateway(provider))),
        raise_server_exceptions=False,
    )

    response = client.post("/api/v1/chat", json={"message": "查询状态"})

    assert response.status_code == 502
    assert private_category not in response.text


def test_api_trace_contains_only_completed_actual_nodes_and_bounds_summary() -> None:
    long_goal = "bounded-goal-" * 100
    provider = MockModelProvider(
        structured_responses=[
            _understanding(),
            {
                "action": "REPLY",
                "goal": long_goal,
                "rationale": "使用当前上下文回复",
            },
        ],
        responses=["已根据当前可确认信息回复。"],
        provider_name="retest",
    )
    client = TestClient(
        create_app(runtime=OpsAgentRuntime(_gateway(provider))),
        raise_server_exceptions=False,
    )

    response = client.post("/api/v1/chat", json={"message": "请简要回复"})

    assert response.status_code == 200
    trace = response.json()["trace"]
    assert [entry["node"] for entry in trace] == [
        "understand_request",
        "decide_action",
        "generate_response",
    ]
    assert all(entry["status"] == "completed" for entry in trace)
    assert all("planned" not in entry["summary"].lower() for entry in trace)
    decision_trace = next(
        entry for entry in trace if entry["node"] == "decide_action"
    )
    assert len(decision_trace["summary"]) <= 500
    assert decision_trace["summary"].endswith("…")


def test_trace_event_constructor_bounds_untrusted_summary_before_api_projection(
) -> None:
    event = AgentTraceEvent(
        node="test",
        task=ModelTask.ACTION_DECISION,
        profile="CHEAP",
        status="completed",
        summary="  x" * 1_000,
    )

    assert len(event.summary) == 500
    assert event.summary.endswith("…")
