"""Safe, request-correlated diagnostics for structured Agent nodes."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Coroutine, Iterable
from dataclasses import asdict
from typing import Any, TypeVar

import pytest
from fastapi.testclient import TestClient

from opsmind import (
    ActionDecisionOutput,
    MockModelProvider,
    ModelGateway,
    ModelInvocationError,
    ModelProfile,
    ModelRoute,
    ModelStructuredOutputError,
    ModelTask,
    OpsAgentState,
    RequestUnderstandingOutput,
    StructuredNodeFailureDiagnostic,
    run_ops_agent,
)
from opsmind.api.app import create_app
from opsmind.api.runtime import OpsAgentRuntime

T = TypeVar("T")


def run_async(operation: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(operation)


def gateway(provider: MockModelProvider) -> ModelGateway:
    return ModelGateway(
        routes={
            ModelProfile.CHEAP: ModelRoute(
                profile=ModelProfile.CHEAP,
                provider="mock",
                model="mock-cheap",
            )
        },
        providers={"mock": provider},
    )


def understanding() -> dict[str, object]:
    return {
        "primary_intent": "WORKFLOW_ISSUE",
        "request_type": "DIAGNOSE",
        "symptom": "查询状态",
        "entities": {"work_order_id": "WO20260001"},
        "risk_signal": "NONE",
        "uncertainty": None,
    }


def decision(action: str = "SEARCH") -> dict[str, object]:
    return {
        "action": action,
        "goal": "获取可验证事实",
        "rationale": "当前上下文需要进一步判断",
    }


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


def selection() -> dict[str, object]:
    return {
        "selected_tool": "work_order_query",
        "arguments": {"work_order_id": "WO20260001"},
        "expected_resolution": "确认当前状态",
    }


def review() -> dict[str, object]:
    return {
        "evidence_sufficient": True,
        "summary": "已复核当前状态",
        "confirmed_facts": ["状态已返回"],
        "unresolved_questions": [],
        "recommended_action": "REPLY",
    }


def state() -> OpsAgentState:
    return OpsAgentState(conversation={"current_query": "查询工单状态"})


@pytest.mark.parametrize(
    ("failed_node", "responses", "expected_schema"),
    [
        (
            "understand_request",
            [ModelStructuredOutputError("RAW-UNDERSTANDING-DETAIL")],
            RequestUnderstandingOutput,
        ),
        (
            "decide_action",
            [understanding(), ModelStructuredOutputError("RAW-DECISION-DETAIL")],
            ActionDecisionOutput,
        ),
        (
            "select_tool",
            [
                understanding(),
                decision(),
                ModelStructuredOutputError("RAW-SELECTION-DETAIL"),
            ],
            "ToolSelectionOutput",
        ),
        (
            "review_tool_result",
            [
                understanding(),
                decision(),
                selection(),
                ModelStructuredOutputError("RAW-REVIEW-DETAIL"),
            ],
            "ToolResultReviewOutput",
        ),
    ],
)
def test_each_structured_node_attaches_only_allowlisted_diagnostic(
    failed_node: str,
    responses: Iterable[object],
    expected_schema: type[Any] | str,
) -> None:
    response_list = list(responses)
    provider = MockModelProvider(structured_responses=response_list)

    with pytest.raises(ModelStructuredOutputError) as captured:
        run_async(run_ops_agent(state(), gateway(provider)))

    diagnostic = captured.value.diagnostic
    assert isinstance(diagnostic, StructuredNodeFailureDiagnostic)
    expected_name = (
        expected_schema
        if isinstance(expected_schema, str)
        else expected_schema.__name__
    )
    assert asdict(diagnostic) == {
        "node": failed_node,
        "expected_schema_name": expected_name,
        "logical_profile": "CHEAP",
        "category": "schema_mismatch",
    }
    assert "RAW-" not in json.dumps(asdict(diagnostic))
    assert provider.invocation_count == len(response_list)


def test_api_logs_request_correlated_safe_diagnostic_and_keeps_error_generic(
    caplog: pytest.LogCaptureFixture,
) -> None:
    raw_detail = "RAW-PROVIDER-PAYLOAD-PRIVATE"
    provider = MockModelProvider(
        structured_responses=[ModelInvocationError(raw_detail)]
    )
    app = create_app(runtime=OpsAgentRuntime(gateway(provider)))
    client = TestClient(app, raise_server_exceptions=False)

    with caplog.at_level(logging.WARNING, logger="opsmind.api"):
        response = client.post("/api/v1/chat", json={"message": "查询状态"})

    assert response.status_code == 502
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "request_id"}
    assert body["error"]["code"] == "MODEL_INVOCATION_FAILED"
    request_id = response.headers["X-Request-ID"]
    assert body["error"]["request_id"] == request_id

    records = [
        record
        for record in caplog.records
        if record.name == "opsmind.api"
        and record.getMessage().startswith("structured_node_failure ")
    ]
    assert len(records) == 1
    message = records[0].getMessage()
    assert f"request_id={request_id}" in message
    assert "node=understand_request" in message
    assert "expected_schema_name=RequestUnderstandingOutput" in message
    assert "logical_profile=CHEAP" in message
    assert "category=invocation_failed" in message
    assert raw_detail not in message
    assert raw_detail not in response.text
    assert provider.invocation_count == 1


def test_failure_diagnostic_does_not_change_success_trace_semantics() -> None:
    provider = MockModelProvider(
        structured_responses=[
            understanding(),
            decision(),
            selection(),
            review(),
            decision("REPLY"),
            grounded_plan(),
        ],
        responses=[],
    )
    run_result = run_async(OpsAgentRuntime(gateway(provider)).run_with_trace(state()))
    result = run_result.state
    events = run_result.events

    assert result.response.message == (
        "当前没有可引用的来源字段，无法基于只读证据给出事实回复。"
    )
    assert all(event.status == "completed" for event in events)
    assert [event.node for event in events] == [
        "understand_request",
        "decide_action",
        "select_tool",
        "execute_tool",
        "review_tool_result",
        "decide_action",
        "generate_response",
    ]
    assert all(
        event.task in {
            ModelTask.REQUEST_UNDERSTANDING,
            ModelTask.ACTION_DECISION,
            ModelTask.TOOL_SELECTION,
            ModelTask.TOOL_RESULT_REVIEW,
            ModelTask.RESPONSE_GENERATION,
        }
        for event in events
    )


__all__ = []
