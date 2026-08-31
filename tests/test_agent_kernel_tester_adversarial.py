"""Independent adversarial coverage for the minimal Agent kernel.

This module intentionally exercises the public kernel boundary rather than
repeating the Developer's happy-path assertions.  It contains no product
fixtures or provider credentials and does not make network calls.
"""

from __future__ import annotations

import asyncio
import json
import math
from collections.abc import Coroutine, Iterable
from datetime import UTC, datetime
from typing import Any, TypeVar

import pytest
from pydantic import BaseModel

from opsmind import (
    ActionDecisionOutput,
    AgentAction,
    AgentInputError,
    MockModelProvider,
    ModelGateway,
    ModelInvocationError,
    ModelProfile,
    ModelRequest,
    ModelResponse,
    ModelRole,
    ModelRoute,
    ModelStructuredOutputError,
    ModelTask,
    OpsAgentState,
    PrimaryIntent,
    RequestUnderstandingOutput,
    StructuredModelResponse,
    build_understanding_context,
    decide_action,
    run_ops_agent,
    understand_request,
)

T = TypeVar("T")


def run_async(operation: Coroutine[Any, Any, T]) -> T:
    """Run an async kernel operation without requiring a pytest plugin."""

    return asyncio.run(operation)


def make_gateway(provider: object) -> ModelGateway:
    """Build the only route the minimal kernel is allowed to use."""

    return ModelGateway(
        routes={
            ModelProfile.CHEAP: ModelRoute(
                profile=ModelProfile.CHEAP,
                provider="tester",
                model="tester-cheap",
            )
        },
        providers={"tester": provider},  # type: ignore[arg-type]
    )


def understanding_response(**overrides: object) -> dict[str, object]:
    response: dict[str, object] = {
        "primary_intent": "WORKFLOW_ISSUE",
        "request_type": "CHECK_STATUS",
        "symptom": "工单长时间未处理",
        "entities": {"work_order_id": "WO20260001"},
        "risk_signal": "NONE",
        "uncertainty": None,
    }
    response.update(overrides)
    return response


def decision_response(**overrides: object) -> dict[str, object]:
    response: dict[str, object] = {
        "action": "SEARCH",
        "goal": "查询当前工单节点",
        "rationale": "已有工单编号，但当前缺少实时业务状态",
    }
    response.update(overrides)
    return response


def state_for(query: str | None = "当前问题") -> OpsAgentState:
    return OpsAgentState(conversation={"current_query": query})


def test_graph_preserves_rich_canonical_state_while_replacing_only_node_sections(
) -> None:
    timestamp = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
    state = OpsAgentState(
        identity={
            "user_id": "user-1",
            "site_id": "site-1",
            "department": "operations",
            "roles": ["operator"],
            "source_context": {"channel": "portal"},
        },
        conversation={
            "thread_id": "thread-1",
            "original_query": "原始问题",
            "current_query": "当前问题",
            "summary": "已有摘要",
            "previous_resolution_status": "UNRESOLVED",
        },
        understanding={
            "primary_intent": "OTHER",
            "request_type": "OTHER",
            "symptom": "旧理解",
            "entities": {"old": "understanding"},
            "risk_signal": "NONE",
        },
        task={
            "objective": "确认流程状态",
            "status": "INVESTIGATING",
            "constraints": ["只读"],
        },
        loop={
            "round_count": 2,
            "tool_call_count": 1,
            "retry_count": 1,
            "max_rounds": 8,
            "max_tool_calls": 12,
            "max_retries": 2,
            "tool_timeout_seconds": 15.0,
        },
        facts={
            "confirmed": ["已确认工单编号"],
            "unresolved_questions": ["当前节点是什么"],
        },
        evidence={
            "items": [
                {
                    "source": "work-order-summary",
                    "summary": "工单已创建",
                    "key_fields": {"work_order_id": "WO20260001"},
                    "metadata": {"raw_tool_payload": "must-stay-out-of-context"},
                    "artifact_ref": "artifact://wo-1",
                    "timestamp": timestamp,
                }
            ]
        },
        decision={
            "action": "REPLY",
            "goal": "旧目标",
            "rationale": "旧理由",
        },
        tool={
            "selected_tool": "private-tool",
            "arguments": {"secret": "must-survive"},
            "expected_resolution": "private-resolution",
        },
        safety={
            "capability": "READ_ONLY",
            "blocked_reason": "private-safety",
        },
        handoff={"required": True, "summary": "private-handoff"},
        response={"message": "private-response", "is_final": True},
    )
    before = state.model_copy(deep=True)
    provider = MockModelProvider(
        structured_responses=[understanding_response(), decision_response()]
    )

    result = run_async(run_ops_agent(state, make_gateway(provider)))

    assert result.understanding.primary_intent is PrimaryIntent.WORKFLOW_ISSUE
    assert result.decision.action is AgentAction.SEARCH
    for field in (
        "identity",
        "conversation",
        "task",
        "loop",
        "facts",
        "evidence",
        "tool",
        "safety",
        "handoff",
        "response",
    ):
        assert getattr(result, field) == getattr(before, field)
    assert result.understanding != before.understanding
    assert result.decision != before.decision


def test_continuation_context_is_complete_and_detached_from_input_state() -> None:
    state = OpsAgentState(
        identity={"source_context": {"channel": "portal", "locale": "zh-CN"}},
        conversation={
            "current_query": "继续处理这个问题",
            "original_query": "最初的问题",
            "summary": "上次已确认账号，但仍未解决",
            "previous_resolution_status": "PARTIALLY_RESOLVED",
        },
    )

    context = build_understanding_context(state)

    assert context.current_query == "继续处理这个问题"
    assert context.original_query == "最初的问题"
    assert context.summary == "上次已确认账号，但仍未解决"
    assert context.previous_resolution_status.value == "PARTIALLY_RESOLVED"
    assert context.source_context == {"channel": "portal", "locale": "zh-CN"}

    context.source_context["channel"] = "mutated"
    assert state.identity.source_context["channel"] == "portal"


def test_decision_request_contains_compact_allowed_projection_only() -> None:
    state = OpsAgentState(
        identity={"source_context": {"hidden": "identity-marker"}},
        conversation={
            "current_query": "当前问题",
            "original_query": "原始问题-marker",
            "summary": "summary-marker",
            "previous_resolution_status": "UNRESOLVED",
        },
        understanding=understanding_response(),
        task={
            "objective": "objective-marker",
            "status": "INVESTIGATING",
            "constraints": ["constraint-marker"],
        },
        facts={
            "confirmed": ["confirmed-marker"],
            "unresolved_questions": ["unresolved-marker"],
        },
        loop={"round_count": 3, "tool_call_count": 2, "retry_count": 1},
        evidence={
            "items": [
                {
                    "source": "tool-summary",
                    "summary": "compact-summary",
                    "key_fields": {"status": "WAITING"},
                    "metadata": {"raw_result": "raw-evidence-marker"},
                    "artifact_ref": "artifact://compact",
                    "timestamp": datetime(2026, 8, 31, tzinfo=UTC),
                }
            ]
        },
        tool={"selected_tool": "tool-internal-marker"},
        safety={"blocked_reason": "safety-internal-marker"},
        handoff={"summary": "handoff-internal-marker"},
        response={"message": "response-internal-marker"},
    )
    provider = MockModelProvider(structured_responses=[decision_response()])

    run_async(decide_action(state, make_gateway(provider)))

    payload = json.loads(provider.history[0].messages[-1].content)
    assert set(payload) == {
        "current_query",
        "understanding",
        "task",
        "facts",
        "evidence",
        "loop",
    }
    serialized = provider.history[0].messages[-1].content
    for marker in (
        "identity-marker",
        "原始问题-marker",
        "summary-marker",
        "raw-evidence-marker",
        "tool-internal-marker",
        "safety-internal-marker",
        "handoff-internal-marker",
        "response-internal-marker",
    ):
        assert marker not in serialized
    assert payload["evidence"] == [
        {
            "source": "tool-summary",
            "summary": "compact-summary",
            "key_fields": {"status": "WAITING"},
            "artifact_ref": "artifact://compact",
            "timestamp": "2026-08-31T00:00:00Z",
        }
    ]


@pytest.mark.parametrize(
    "query",
    [None, "", "   ", "\t\r\n\u3000", "\v\f"],
)
def test_unicode_and_control_whitespace_queries_fail_before_any_model_call(
    query: str | None,
) -> None:
    provider = MockModelProvider(structured_responses=[understanding_response()])

    with pytest.raises(AgentInputError, match="current_query"):
        run_async(run_ops_agent(state_for(query), make_gateway(provider)))

    assert provider.invocation_count == 0


def test_decision_node_also_rejects_missing_query_before_gateway_call() -> None:
    provider = MockModelProvider(structured_responses=[decision_response()])

    with pytest.raises(AgentInputError, match="current_query"):
        run_async(decide_action(state_for(None), make_gateway(provider)))

    assert provider.invocation_count == 0


@pytest.mark.parametrize(
    "entities",
    [
        ["not-an-object"],
        {"score": math.nan},
        {"nested": {"score": math.inf}},
    ],
)
def test_malformed_nested_understanding_payload_never_updates_input_state(
    entities: object,
) -> None:
    provider = MockModelProvider(
        structured_responses=[understanding_response(entities=entities)]
    )
    state = OpsAgentState(
        conversation={"current_query": "当前问题"},
        understanding={
            "primary_intent": "OTHER",
            "request_type": "OTHER",
            "symptom": "pre-existing",
            "entities": {"pre-existing": True},
        },
    )
    before = state.model_copy(deep=True)

    with pytest.raises(ModelStructuredOutputError):
        run_async(run_ops_agent(state, make_gateway(provider)))

    assert provider.invocation_count == 1
    assert state == before


@pytest.mark.parametrize(
    "invalid_decision",
    [
        decision_response(goal=""),
        decision_response(goal=" \t\n"),
        decision_response(rationale=""),
        decision_response(rationale="\u3000\t"),
        decision_response(action="NOT_A_SUPPORTED_ACTION"),
        decision_response(extra_field="must-be-rejected"),
    ],
)
def test_invalid_decision_output_is_rejected_without_partial_input_mutation(
    invalid_decision: dict[str, object],
) -> None:
    provider = MockModelProvider(
        structured_responses=[understanding_response(), invalid_decision]
    )
    state = state_for()
    before = state.model_copy(deep=True)

    with pytest.raises(ModelStructuredOutputError):
        run_async(run_ops_agent(state, make_gateway(provider)))

    assert provider.invocation_count == 2
    assert state == before


def test_direct_node_updates_are_single_section_fragments() -> None:
    provider = MockModelProvider(structured_responses=[understanding_response()])
    state = state_for()

    update = run_async(understand_request(state, make_gateway(provider)))

    assert set(update) == {"understanding"}
    assert set(update["understanding"].model_dump()) == {
        "primary_intent",
        "request_type",
        "symptom",
        "entities",
        "risk_signal",
        "uncertainty",
    }


class SchemaRecordingProvider:
    """Tiny provider adapter that records the caller's structured schema."""

    def __init__(self, responses: Iterable[object]) -> None:
        self.responses = list(responses)
        self.response_models: list[type[BaseModel]] = []
        self.requests: list[ModelRequest] = []

    async def invoke(
        self,
        request: ModelRequest,
        *,
        model: str,
    ) -> ModelResponse:
        raise AssertionError("the kernel must use structured invocation")

    async def invoke_structured(
        self,
        request: ModelRequest,
        response_model: type[BaseModel],
        *,
        model: str,
    ) -> object:
        self.requests.append(request.model_copy(deep=True))
        self.response_models.append(response_model)
        payload = self.responses.pop(0)
        return StructuredModelResponse(
            parsed=response_model.model_validate(payload),
            response=ModelResponse(content="", provider="tester", model=model),
        )


def test_nodes_route_exact_structured_schema_and_prompt_contract_through_gateway(
) -> None:
    provider = SchemaRecordingProvider(
        [understanding_response(), decision_response()]
    )
    gateway = make_gateway(provider)
    state = state_for()

    first_update = run_async(understand_request(state, gateway))
    intermediate = state.model_copy(deep=True)
    intermediate.understanding = first_update["understanding"]
    run_async(decide_action(intermediate, gateway))

    assert provider.response_models == [
        RequestUnderstandingOutput,
        ActionDecisionOutput,
    ]
    assert [request.task for request in provider.requests] == [
        ModelTask.REQUEST_UNDERSTANDING,
        ModelTask.ACTION_DECISION,
    ]
    assert [request.profile for request in provider.requests] == [
        ModelProfile.CHEAP,
        ModelProfile.CHEAP,
    ]
    assert all(
        request.messages[0].role is ModelRole.SYSTEM
        and request.messages[1].role is ModelRole.USER
        and request.messages[0].content.strip()
        for request in provider.requests
    )


def test_raw_provider_failures_are_wrapped_at_each_graph_node_without_fallback(
) -> None:
    provider = MockModelProvider(
        structured_responses=[RuntimeError("first call failed")]
    )
    state = state_for()
    before = state.model_copy(deep=True)

    with pytest.raises(ModelInvocationError, match="structured model provider"):
        run_async(run_ops_agent(state, make_gateway(provider)))

    assert provider.invocation_count == 1
    assert state == before

    provider = MockModelProvider(
        structured_responses=[
            understanding_response(),
            RuntimeError("second call failed"),
        ]
    )
    before = state.model_copy(deep=True)
    with pytest.raises(ModelInvocationError, match="structured model provider"):
        run_async(run_ops_agent(state, make_gateway(provider)))
    assert provider.invocation_count == 2
    assert state == before


def test_two_concurrent_runs_with_one_shared_mock_provider_keep_query_state_isolated(
) -> None:
    provider = MockModelProvider(
        structured_responses=[
            understanding_response(entities={"run": "one"}),
            understanding_response(entities={"run": "two"}),
            decision_response(action="REPLY"),
            decision_response(action="REPLY"),
        ]
    )
    gateway = make_gateway(provider)
    first_state = state_for("query-one")
    second_state = state_for("query-two")

    async def run_both() -> tuple[OpsAgentState, OpsAgentState]:
        return await asyncio.gather(
            run_ops_agent(first_state, gateway),
            run_ops_agent(second_state, gateway),
        )

    first_result, second_result = run_async(run_both())

    assert first_result.conversation.current_query == "query-one"
    assert second_result.conversation.current_query == "query-two"
    assert first_result.understanding.entities == {"run": "one"}
    assert second_result.understanding.entities == {"run": "two"}
    assert first_result.decision.action is AgentAction.REPLY
    assert second_result.decision.action is AgentAction.REPLY
    assert first_state == state_for("query-one")
    assert second_state == state_for("query-two")
    assert provider.invocation_count == 4
    assert [invocation.task for invocation in provider.history].count(
        ModelTask.REQUEST_UNDERSTANDING
    ) == 2
    assert [invocation.task for invocation in provider.history].count(
        ModelTask.ACTION_DECISION
    ) == 2
