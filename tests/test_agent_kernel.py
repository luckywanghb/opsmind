"""Developer coverage for the minimal LangGraph Agent kernel."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Coroutine
from typing import Any, TypeVar

import pytest

from opsmind import (
    ActionDecisionOutput,
    AgentAction,
    AgentInputError,
    MockModelProvider,
    ModelGateway,
    ModelInvocationError,
    ModelProfile,
    ModelRoute,
    ModelStructuredOutputError,
    ModelTask,
    OpsAgentState,
    PrimaryIntent,
    RequestType,
    StructuredModelResponse,
    ToolRegistry,
    build_decision_context,
    build_ops_graph,
    build_understanding_context,
    run_ops_agent,
)
from opsmind.agent.nodes import decide_action, understand_request

T = TypeVar("T")


def run_async(operation: Coroutine[Any, Any, T]) -> T:
    """Run one async kernel operation without requiring an extra plugin."""

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


def selection_response(**overrides: object) -> dict[str, object]:
    response: dict[str, object] = {
        "selected_tool": "work_order_query",
        "arguments": {"work_order_id": "WO20260001"},
        "expected_resolution": "确认当前工单节点",
    }
    response.update(overrides)
    return response


def review_response(**overrides: object) -> dict[str, object]:
    response: dict[str, object] = {
        "evidence_sufficient": True,
        "summary": "已确认当前工单状态。",
        "confirmed_facts": ["工单正在审批"],
        "unresolved_questions": [],
        "recommended_action": "REPLY",
    }
    response.update(overrides)
    return response


def final_decision_response() -> dict[str, object]:
    return decision_response(
        action="REPLY",
        goal="基于证据回复",
        rationale="证据已足够",
    )


def initial_state(**conversation: object) -> OpsAgentState:
    values: dict[str, object] = {"current_query": "WO20260001为什么一直没处理？"}
    values.update(conversation)
    return OpsAgentState(conversation=values)


def test_graph_compiles_with_the_bounded_read_only_loop_topology() -> None:
    compiled = build_ops_graph(gateway(MockModelProvider()))
    graph = compiled.get_graph()

    assert {
        "__start__",
        "understand_request",
        "decide_action",
        "select_tool",
        "execute_tool",
        "review_tool_result",
        "generate_clarification",
        "generate_response",
        "generate_handoff",
        "runtime_limit",
        "close_conversation",
        "__end__",
    } == set(graph.nodes)
    edges = {(edge.source, edge.target) for edge in graph.edges}
    assert {
        ("__start__", "understand_request"),
        ("understand_request", "decide_action"),
        ("decide_action", "select_tool"),
        ("select_tool", "execute_tool"),
        ("execute_tool", "review_tool_result"),
        ("review_tool_result", "decide_action"),
        ("decide_action", "generate_clarification"),
        ("decide_action", "generate_response"),
        ("decide_action", "generate_handoff"),
        ("decide_action", "close_conversation"),
        ("runtime_limit", "generate_handoff"),
    } <= edges


def test_happy_path_returns_typed_state_and_completes_the_tool_loop() -> None:
    provider = MockModelProvider(
        structured_responses=[
            understanding_response(),
            decision_response(),
            selection_response(),
            review_response(),
            final_decision_response(),
        ],
        responses=["工单正在审批。"],
    )

    result = run_async(run_ops_agent(initial_state(), gateway(provider)))

    assert isinstance(result, OpsAgentState)
    assert result.understanding.primary_intent is PrimaryIntent.WORKFLOW_ISSUE
    assert result.understanding.request_type is RequestType.CHECK_STATUS
    assert result.understanding.entities["work_order_id"] == "WO20260001"
    assert result.decision.action is AgentAction.REPLY
    assert result.tool.selected_tool == "work_order_query"
    assert result.response.message == "工单正在审批。"
    assert provider.invocation_count == 6


def test_model_calls_use_expected_task_order_and_cheap_profile() -> None:
    provider = MockModelProvider(
        structured_responses=[
            understanding_response(),
            decision_response(),
            selection_response(),
            review_response(),
            final_decision_response(),
        ],
        responses=["工单正在审批。"],
    )

    run_async(run_ops_agent(initial_state(), gateway(provider)))

    assert [invocation.task for invocation in provider.history] == [
        ModelTask.REQUEST_UNDERSTANDING,
        ModelTask.ACTION_DECISION,
        ModelTask.TOOL_SELECTION,
        ModelTask.TOOL_RESULT_REVIEW,
        ModelTask.ACTION_DECISION,
        ModelTask.RESPONSE_GENERATION,
    ]
    assert all(
        invocation.profile is ModelProfile.CHEAP for invocation in provider.history
    )
    assert [invocation.request.metadata["node"] for invocation in provider.history] == [
        "understand_request",
        "decide_action",
        "select_tool",
        "review_tool_result",
        "decide_action",
        "generate_response",
    ]


def test_decision_context_contains_the_first_node_update() -> None:
    provider = MockModelProvider(
        structured_responses=[
            understanding_response(),
            decision_response(),
            selection_response(),
            review_response(),
            final_decision_response(),
        ],
        responses=["工单正在审批。"],
    )

    run_async(run_ops_agent(initial_state(), gateway(provider)))

    second_context = json.loads(provider.history[1].messages[-1].content)
    assert second_context["understanding"] == {
        "primary_intent": "WORKFLOW_ISSUE",
        "request_type": "CHECK_STATUS",
        "symptom": "工单长时间未处理",
        "entities": {"work_order_id": "WO20260001"},
        "risk_signal": "NONE",
    }


def test_context_builders_expose_only_node_specific_fields() -> None:
    state = OpsAgentState(
        identity={"source_context": {"channel": "support_portal"}},
        conversation={
            "current_query": "当前问题",
            "original_query": "原始问题",
            "summary": "已有摘要",
            "previous_resolution_status": "UNRESOLVED",
        },
        understanding=understanding_response(),
        task={"objective": "确认状态", "status": "INVESTIGATING"},
        facts={
            "confirmed": ["已有工单编号"],
            "unresolved_questions": ["当前节点是什么"],
        },
        loop={"round_count": 1},
        tool={"selected_tool": "must-not-be-visible"},
        safety={"blocked_reason": "must-not-be-visible"},
    )

    understanding_context = build_understanding_context(state)
    assert set(understanding_context.model_dump()) == {
        "current_query",
        "original_query",
        "summary",
        "previous_resolution_status",
        "source_context",
    }

    decision_context = build_decision_context(state, [])
    assert set(decision_context.model_dump()) == {
        "current_query",
        "understanding",
        "task",
        "facts",
        "evidence",
        "latest_review",
        "available_tools",
        "loop",
    }
    assert "must-not-be-visible" in decision_context.model_dump_json()


def test_understanding_request_does_not_dump_unrelated_state() -> None:
    state = OpsAgentState(
        conversation={"current_query": "当前问题"},
        evidence={"items": []},
        tool={"selected_tool": "private-tool"},
        safety={"blocked_reason": "private-safety"},
    )
    provider = MockModelProvider(structured_responses=[understanding_response()])

    run_async(understand_request(state, gateway(provider)))

    content = provider.history[0].messages[-1].content
    payload = json.loads(content)
    assert payload["current_query"] == "当前问题"
    assert "evidence" not in payload
    assert "tool" not in payload
    assert "safety" not in payload
    assert "private-tool" not in content
    assert "private-safety" not in content


@pytest.mark.parametrize("query", [None, "", "   "])
def test_missing_or_whitespace_query_fails_before_gateway_call(
    query: str | None,
) -> None:
    provider = MockModelProvider(
        structured_responses=[
            understanding_response(),
            decision_response(),
            selection_response(),
            review_response(),
            final_decision_response(),
        ],
        responses=["工单正在审批。"],
    )
    state = OpsAgentState(conversation={"current_query": query})

    with pytest.raises(AgentInputError, match="current_query"):
        run_async(run_ops_agent(state, gateway(provider)))

    assert provider.invocation_count == 0


def test_invalid_understanding_output_fails_without_a_partial_state_update() -> None:
    provider = MockModelProvider(
        structured_responses=[understanding_response(primary_intent="INVALID")]
    )
    state = initial_state()

    with pytest.raises(ModelStructuredOutputError):
        run_async(run_ops_agent(state, gateway(provider)))

    assert provider.invocation_count == 1
    assert state.understanding.primary_intent is None
    assert state.decision.action is None


def test_extra_understanding_field_is_rejected_at_structured_boundary() -> None:
    provider = MockModelProvider(
        structured_responses=[understanding_response(confidence=0.95)]
    )

    with pytest.raises(ModelStructuredOutputError):
        run_async(run_ops_agent(initial_state(), gateway(provider)))


@pytest.mark.parametrize(
    "missing_field",
    [
        "primary_intent",
        "request_type",
        "symptom",
        "entities",
        "risk_signal",
        "uncertainty",
    ],
)
def test_missing_transient_understanding_field_is_rejected(
    missing_field: str,
) -> None:
    response = understanding_response()
    del response[missing_field]
    provider = MockModelProvider(structured_responses=[response])

    with pytest.raises(ModelStructuredOutputError):
        run_async(run_ops_agent(initial_state(), gateway(provider)))

    assert provider.invocation_count == 1


def test_invalid_decision_output_does_not_write_decision_state() -> None:
    provider = MockModelProvider(
        structured_responses=[understanding_response(), {"action": "SEARCH"}]
    )
    state = initial_state()
    valid_understanding = run_async(
        understand_request(state, gateway(provider))
    )["understanding"]
    state_after_understanding = state.model_copy(deep=True)
    state_after_understanding.understanding = valid_understanding

    with pytest.raises(ModelStructuredOutputError):
        run_async(
            decide_action(state_after_understanding, gateway(provider), ToolRegistry())
        )

    assert state_after_understanding.understanding.primary_intent is (
        PrimaryIntent.WORKFLOW_ISSUE
    )
    assert state_after_understanding.decision.action is None
    assert provider.invocation_count == 2


def test_gateway_invocation_error_propagates_without_fallback_business_logic() -> None:
    provider = MockModelProvider(
        structured_responses=[ModelInvocationError("provider offline")]
    )

    with pytest.raises(ModelInvocationError, match="provider offline"):
        run_async(run_ops_agent(initial_state(), gateway(provider)))

    assert provider.invocation_count == 1


def test_second_gateway_invocation_error_propagates_after_valid_first_node() -> None:
    provider = MockModelProvider(
        structured_responses=[
            understanding_response(),
            ModelInvocationError("provider offline"),
        ]
    )

    with pytest.raises(ModelInvocationError, match="provider offline"):
        run_async(run_ops_agent(initial_state(), gateway(provider)))

    assert provider.invocation_count == 2


def test_run_does_not_mutate_input_or_leak_nested_mutations() -> None:
    provider = MockModelProvider(
        structured_responses=[
            understanding_response(),
            decision_response(),
            selection_response(),
            review_response(),
            final_decision_response(),
        ],
        responses=["工单正在审批。"],
    )
    state = initial_state()
    before = state.model_copy(deep=True)

    result = run_async(run_ops_agent(state, gateway(provider)))

    assert state == before
    result.understanding.entities["new"] = "output-only"
    assert "new" not in state.understanding.entities


def test_public_kernel_api_exports_are_available_from_root_package() -> None:
    assert ActionDecisionOutput.model_fields["action"].annotation is AgentAction
    assert isinstance(build_ops_graph(gateway(MockModelProvider())), object)
    assert callable(build_understanding_context)
    assert callable(build_decision_context)
    assert callable(run_ops_agent)
    assert StructuredModelResponse.__name__ == "StructuredModelResponse"
