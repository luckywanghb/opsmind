"""Developer coverage for the generic read-only tool loop.

The D01-D03 examples in this module are fixtures.  The graph never sees a
case identifier and every tool choice is supplied by the model fixture through
the same registered-tool contract used by a real provider.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Coroutine, Iterable
from typing import Any, TypeVar

import pytest

from opsmind import (
    IncidentQueryResponse,
    MockModelProvider,
    ModelGateway,
    ModelInvocationError,
    ModelProfile,
    ModelRoute,
    ModelTask,
    OpsAgentState,
    PermissionQueryResponse,
    RegisteredTool,
    ToolArgumentsError,
    ToolExecutionError,
    ToolMode,
    ToolPolicyError,
    ToolRegistry,
    ToolResultStatus,
    ToolSpec,
    UnknownToolError,
    WorkOrderQueryRequest,
    WorkOrderQueryResponse,
    build_default_tool_registry,
    run_ops_agent,
    run_ops_agent_with_trace,
)

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


def understanding(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "primary_intent": "WORKFLOW_ISSUE",
        "request_type": "DIAGNOSE",
        "symptom": "当前请求需要查询状态",
        "entities": {"work_order_id": "WO20260001"},
        "risk_signal": "NONE",
        "uncertainty": None,
    }
    payload.update(overrides)
    return payload


def decision(action: str = "SEARCH", **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "action": action,
        "goal": "获取当前可验证事实",
        "rationale": "当前上下文仍缺少足够证据",
    }
    payload.update(overrides)
    return payload


def selection(
    tool_name: str,
    arguments: dict[str, object],
    **overrides: object,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "selected_tool": tool_name,
        "arguments": arguments,
        "expected_resolution": "确认与当前问题相关的事实",
    }
    payload.update(overrides)
    return payload


def review(
    *,
    sufficient: bool,
    summary: str,
    facts: Iterable[str] = (),
    unresolved: Iterable[str] = (),
    action: str = "REPLY",
) -> dict[str, object]:
    return {
        "evidence_sufficient": sufficient,
        "summary": summary,
        "confirmed_facts": list(facts),
        "unresolved_questions": list(unresolved),
        "recommended_action": action,
    }


def grounded_response_plan(
    action: str = "REPLY",
    *,
    refs: Iterable[tuple[str, str]] = (),
    intent: str | None = None,
    limitation: str = "NONE",
    clarification_target: str = "GENERIC",
) -> dict[str, object]:
    """Explicit terminal fixture for the evidence-bound renderer."""

    inferred_intent = {
        "REPLY": "FACTS",
        "ASK_USER": "CLARIFICATION",
        "TRANSFER_HUMAN": "HANDOFF",
        "END_CONVERSATION": "CLOSE",
    }[action]
    return {
        "terminal_mode": action,
        "presentation_intent": intent or inferred_intent,
        "evidence_references": [
            {"evidence_id": evidence_id, "path": path}
            for evidence_id, path in refs
        ],
        "limitation": limitation,
        "clarification_target": clarification_target,
    }


def state(query: str, **identity: object) -> OpsAgentState:
    return OpsAgentState(
        identity=identity,
        conversation={"current_query": query},
    )


def test_default_registry_exposes_only_typed_read_only_tools() -> None:
    registry = build_default_tool_registry()

    assert registry.names == (
        "work_order_query",
        "permission_query",
        "incident_query",
    )
    descriptions = registry.describe()
    assert [item["name"] for item in descriptions] == list(registry.names)
    assert all(item["mode"] == ToolMode.READ_ONLY.value for item in descriptions)
    assert all(
        "input_schema" in item and "output_schema" in item
        for item in descriptions
    )


@pytest.mark.asyncio
async def test_synthetic_adapters_return_found_and_typed_not_found() -> None:
    registry = build_default_tool_registry()

    work_order = await registry.execute(
        "work_order_query",
        {"work_order_id": "WO20260001"},
    )
    assert isinstance(work_order.output, WorkOrderQueryResponse)
    assert work_order.output.result_status is ToolResultStatus.FOUND
    assert work_order.output.current_node == "设备主管审批"

    permission = await registry.execute(
        "permission_query",
        {"user_id": "U10023", "system_id": "EquipFlow"},
    )
    assert isinstance(permission.output, PermissionQueryResponse)
    assert permission.output.missing_permissions == ["EQUIPMENT_LEDGER_VIEW"]

    incident = await registry.execute(
        "incident_query",
        {"system_id": "EquipFlow", "site": "星川基地"},
    )
    assert isinstance(incident.output, IncidentQueryResponse)
    assert incident.output.incident_status == "ACTIVE"

    unseen = await registry.execute(
        "work_order_query",
        {"work_order_id": "WO-UNSEEN-42"},
    )
    assert isinstance(unseen.output, WorkOrderQueryResponse)
    assert unseen.output.result_status is ToolResultStatus.NOT_FOUND
    assert unseen.output.work_order_id == "WO-UNSEEN-42"


@pytest.mark.asyncio
async def test_registry_rejects_unknown_invalid_and_write_calls() -> None:
    registry = build_default_tool_registry()

    with pytest.raises(UnknownToolError):
        registry.validate_call("not_registered", {})
    with pytest.raises(ToolArgumentsError):
        registry.validate_call("work_order_query", {"wrong": "field"})

    async def write_handler(
        request: WorkOrderQueryRequest,
    ) -> WorkOrderQueryResponse:
        del request
        return WorkOrderQueryResponse(
            result_status=ToolResultStatus.FOUND,
            work_order_id="WO-WRITE",
        )

    write_registry = ToolRegistry(
        [
            RegisteredTool(
                spec=ToolSpec(
                    name="write_like_tool",
                    description="Fixture write capability",
                    mode=ToolMode.WRITE,
                ),
                request_model=WorkOrderQueryRequest,
                response_model=WorkOrderQueryResponse,
                handler=write_handler,
            )
        ]
    )
    with pytest.raises(ToolPolicyError):
        await write_registry.execute(
            "write_like_tool",
            {"work_order_id": "WO-WRITE"},
        )


@pytest.mark.asyncio
async def test_registry_enforces_the_stricter_state_and_tool_timeout() -> None:
    async def slow_handler(
        request: WorkOrderQueryRequest,
    ) -> WorkOrderQueryResponse:
        del request
        await asyncio.sleep(0.05)
        return WorkOrderQueryResponse(
            result_status=ToolResultStatus.FOUND,
            work_order_id="WO-SLOW",
        )

    registry = ToolRegistry(
        [
            RegisteredTool(
                spec=ToolSpec(
                    name="slow_query",
                    description="Fixture slow read-only query",
                    mode=ToolMode.READ_ONLY,
                    timeout_seconds=0.01,
                ),
                request_model=WorkOrderQueryRequest,
                response_model=WorkOrderQueryResponse,
                handler=slow_handler,
            )
        ]
    )

    with pytest.raises(ToolExecutionError) as error:
        await registry.execute(
            "slow_query",
            {"work_order_id": "WO-SLOW"},
            timeout_seconds=0.02,
        )
    assert error.value.code == "TOOL_TIMEOUT"


def test_d01_work_order_runs_selection_execution_review_redecision_and_reply() -> None:
    provider = MockModelProvider(
        structured_responses=[
            understanding(),
            decision(),
            selection("work_order_query", {"work_order_id": "WO20260001"}),
            review(
                sufficient=True,
                summary=(
                    "工单正在设备主管审批，当前处理人为 U10108，"
                    "已等待 4 小时，未标记异常。"
                ),
                facts=[
                    "状态为 APPROVING",
                    "当前节点为设备主管审批",
                    "等待 4 小时",
                    "abnormal=false",
                ],
            ),
            decision("REPLY", goal="基于已复核工单事实回复", rationale="证据已足够"),
            grounded_response_plan(
                refs=[
                    ("E1", "key_fields.status"),
                    ("E1", "key_fields.current_node"),
                    ("E1", "key_fields.current_handler"),
                    ("E1", "key_fields.waiting_hours"),
                    ("E1", "key_fields.abnormal"),
                ],
                intent="FACTS_WITH_LIMITATION",
                limitation="MISSING_THRESHOLD",
            ),
        ],
        responses=[],
    )

    result, events = run_async(
        run_ops_agent_with_trace(
            state("WO20260001为什么一直没处理？"),
            gateway(provider),
        )
    )

    assert result.task.status.value == "RESOLVED"
    assert result.response.is_final is True
    assert result.response.message is not None
    assert result.loop.tool_call_count == 1
    assert result.tool.selected_tool == "work_order_query"
    assert result.tool.evidence_sufficient is True
    assert result.evidence.items[0].source == "work_order_query"
    assert result.evidence.items[0].key_fields["current_node"] == "设备主管审批"
    assert "已找到工单状态快照" not in result.model_dump_json()
    assert [event.node for event in events] == [
        "understand_request",
        "decide_action",
        "select_tool",
        "execute_tool",
        "review_tool_result",
        "decide_action",
        "generate_response",
    ]
    assert events[2].task is ModelTask.TOOL_SELECTION
    assert events[3].profile == "HARNESS"
    assert events[4].task is ModelTask.TOOL_RESULT_REVIEW
    assert events[-1].summary == "已生成最终回复"
    review_prompt = provider.history[3].messages[0].content
    assert "等待时长不等于未超时" in review_prompt
    assert "false" in review_prompt
    response_prompt = provider.history[5].messages[0].content
    assert "elapsed duration is not an SLA" in response_prompt


def test_latest_review_capabilities_and_source_fields_reach_later_contexts() -> None:
    provider = MockModelProvider(
        structured_responses=[
            understanding(),
            decision(),
            selection("work_order_query", {"work_order_id": "WO20260001"}),
            review(
                sufficient=True,
                summary="已复核当前工单快照；审批阈值未由当前工具返回。",
                facts=["当前节点为设备主管审批", "处理人为 U10108", "等待 4 小时"],
                unresolved=["审批阈值未由当前工具返回"],
            ),
            decision(
                "REPLY",
                goal="基于当前快照给出有边界的回复",
                rationale="当前事实足够",
            ),
            grounded_response_plan(),
        ],
        responses=[],
    )

    run_async(
        run_ops_agent(
            state("WO20260001为什么一直没处理？"),
            gateway(provider),
        )
    )

    selection_context = json.loads(provider.history[2].messages[1].content)
    review_context = json.loads(provider.history[3].messages[1].content)
    redecision_context = json.loads(provider.history[4].messages[1].content)
    response_context = json.loads(provider.history[5].messages[1].content)

    assert [item["name"] for item in selection_context["available_tools"]] == [
        "work_order_query",
        "permission_query",
        "incident_query",
    ]
    assert all(
        item["mode"] == "READ_ONLY"
        for item in selection_context["available_tools"]
    )
    assert review_context["expected_resolution"] == "确认与当前问题相关的事实"
    assert review_context["selected_tool_schema"]["properties"]["waiting_hours"][
        "description"
    ].startswith("Elapsed waiting duration")
    assert "message" not in review_context["selected_tool_schema"]["properties"]
    assert review_context["available_tools"][0]["name"] == "work_order_query"
    assert redecision_context["latest_review"] == {
        "selected_tool": "work_order_query",
        "expected_resolution": "确认与当前问题相关的事实",
        "review_summary": "已复核当前工单快照；审批阈值未由当前工具返回。",
        "evidence_sufficient": True,
        "recommended_action": "REPLY",
        "result_status": "found",
    }
    for context in (redecision_context, response_context):
        assert context["available_tools"][0]["name"] == "work_order_query"
        key_fields = context["evidence"][0]["key_fields"]
        assert key_fields["current_handler"] == "U10108"
        assert key_fields["waiting_hours"] == 4.0
        assert key_fields["abnormal"] is False
        assert "已找到工单状态快照" not in json.dumps(context, ensure_ascii=False)


@pytest.mark.parametrize(
    ("review_sufficient", "review_action", "decision_action"),
    [
        (True, "REPLY", "ASK_USER"),
        (False, "ASK_USER", "REPLY"),
    ],
)
def test_review_recommendation_is_advisory_to_fresh_action_decision(
    review_sufficient: bool,
    review_action: str,
    decision_action: str,
) -> None:
    provider = MockModelProvider(
        structured_responses=[
            understanding(),
            decision(),
            selection("work_order_query", {"work_order_id": "WO20260001"}),
            review(
                sufficient=review_sufficient,
                summary="已复核当前只读快照。",
                facts=["返回了类型化状态字段"],
                action=review_action,
            ),
            decision(
                decision_action,
                goal="由最新动作决策继续处理",
                rationale="重新评估当前上下文",
            ),
            grounded_response_plan(decision_action),
        ],
        responses=[],
    )

    result = run_async(
        run_ops_agent(
            state("请查询工单当前状态"),
            gateway(provider),
        )
    )

    assert result.decision.action.value == decision_action
    assert provider.history[4].task is ModelTask.ACTION_DECISION
    assert provider.history[-1].task is (
        ModelTask.CLARIFICATION
        if decision_action == "ASK_USER"
        else ModelTask.RESPONSE_GENERATION
    )
    terminal_context = json.loads(provider.history[-1].messages[1].content)
    # Terminal grounding sees only typed source fields; review recommendation
    # remains advisory control-plane state and is intentionally excluded.
    assert "latest_review" not in terminal_context
    assert terminal_context["available_tools"][0]["name"] == "work_order_query"
    terminal_prompt = provider.history[-1].messages[0].content
    assert "unexecuted call" in terminal_prompt
    assert "result not present in evidence" in terminal_prompt
    assert result.task.status.value == (
        "WAITING_USER" if decision_action == "ASK_USER" else "RESOLVED"
    )


def test_found_snapshot_can_answer_with_explicit_unknown_threshold() -> None:
    async def alternate_work_order(
        request: WorkOrderQueryRequest,
    ) -> WorkOrderQueryResponse:
        return WorkOrderQueryResponse(
            result_status=ToolResultStatus.FOUND,
            work_order_id=request.work_order_id,
            status="QUEUED",
            current_node="夜班审批",
            current_handler="U90001",
            waiting_hours=2.5,
            abnormal=False,
        )

    registry = ToolRegistry(
        [
            RegisteredTool(
                spec=ToolSpec(
                    name="work_order_query",
                    description="Alternate fixture status query",
                    mode=ToolMode.READ_ONLY,
                ),
                request_model=WorkOrderQueryRequest,
                response_model=WorkOrderQueryResponse,
                handler=alternate_work_order,
            )
        ]
    )
    provider = MockModelProvider(
        structured_responses=[
            understanding(
                entities={"work_order_id": "WO-UNSEEN-BUT-REGISTERED"},
            ),
            decision(),
            selection(
                "work_order_query",
                {"work_order_id": "WO-UNSEEN-BUT-REGISTERED"},
            ),
            review(
                sufficient=True,
                summary="已确认夜班审批快照；审批阈值未由当前工具返回。",
                facts=[
                    "当前节点为夜班审批",
                    "处理人为 U90001",
                    "等待 2.5 小时",
                    "源标记 abnormal=false",
                ],
                unresolved=["审批阈值未由当前工具返回"],
            ),
            decision(
                "REPLY",
                goal="回复当前快照并说明限制",
                rationale="当前事实足以给出有边界的回复",
            ),
            grounded_response_plan(
                refs=[
                    ("E1", "key_fields.status"),
                    ("E1", "key_fields.current_node"),
                    ("E1", "key_fields.current_handler"),
                    ("E1", "key_fields.waiting_hours"),
                    ("E1", "key_fields.abnormal"),
                ],
                intent="FACTS_WITH_LIMITATION",
                limitation="MISSING_THRESHOLD",
            ),
        ],
        responses=[],
    )

    result = run_async(
        run_ops_agent(
            state("WO-UNSEEN-BUT-REGISTERED当前状态？"),
            gateway(provider),
            registry,
        )
    )

    assert result.task.status.value == "RESOLVED"
    assert result.response.message is not None
    assert "未提供" not in result.evidence.items[0].key_fields
    assert result.evidence.items[0].key_fields["current_handler"] == "U90001"
    assert result.facts.unresolved_questions == ["审批阈值未由当前工具返回"]
    final_context = json.loads(provider.history[5].messages[1].content)
    assert final_context["available_tools"] == [
        {
            "name": "work_order_query",
            "description": "Alternate fixture status query",
            "mode": "READ_ONLY",
        }
    ]
    assert final_context["evidence"][0]["key_fields"]["waiting_hours"] == 2.5


@pytest.mark.parametrize(
    ("query", "understanding_overrides", "tool_name", "arguments", "facts"),
    [
        (
            "别人都有设备台账菜单，为什么我没有？",
            {
                "primary_intent": "ACCESS_ISSUE",
                "entities": {"system_id": "EquipFlow", "user_id": "U10023"},
            },
            "permission_query",
            {"user_id": "U10023", "system_id": "EquipFlow"},
            ["角色包含 EQUIPMENT_VIEWER", "缺少 EQUIPMENT_LEDGER_VIEW"],
        ),
        (
            "今天整个星川基地的人都进不去EquipFlow。",
            {
                "primary_intent": "ACCESS_ISSUE",
                "risk_signal": "BROAD_OUTAGE",
                "entities": {"system_id": "EquipFlow", "site": "星川基地"},
            },
            "incident_query",
            {"system_id": "EquipFlow", "site": "星川基地"},
            ["事件状态为 ACTIVE", "影响星川基地用户"],
        ),
    ],
)
def test_d02_and_d03_use_model_selected_tool_without_case_routing(
    query: str,
    understanding_overrides: dict[str, object],
    tool_name: str,
    arguments: dict[str, object],
    facts: list[str],
) -> None:
    provider = MockModelProvider(
        structured_responses=[
            understanding(**understanding_overrides),
            decision(),
            selection(tool_name, arguments),
            review(
                sufficient=True,
                summary="已复核与请求相关的只读事实。",
                facts=facts,
                action="REPLY" if tool_name == "permission_query" else "TRANSFER_HUMAN",
            ),
            decision(
                "REPLY" if tool_name == "permission_query" else "TRANSFER_HUMAN",
                goal="基于已复核事实继续处理",
                rationale="模型判断当前证据足够完成下一步",
            ),
            grounded_response_plan(
                "REPLY" if tool_name == "permission_query" else "TRANSFER_HUMAN",
                refs=(
                    [
                        ("E1", "key_fields.roles"),
                        ("E1", "key_fields.missing_permissions"),
                    ]
                    if tool_name == "permission_query"
                    else [
                        ("E1", "key_fields.incident_status"),
                        ("E1", "key_fields.impact"),
                    ]
                ),
                intent=(
                    "LIMITED_FACTS"
                    if tool_name == "permission_query"
                    else "FACTS_WITH_LIMITATION"
                ),
                limitation=(
                    "ENTITLEMENT_UNAVAILABLE"
                    if tool_name == "permission_query"
                    else "REMEDIATION_UNAVAILABLE"
                ),
            ),
        ],
        responses=[],
    )
    identity = {"user_id": "U10023"} if tool_name == "permission_query" else {}

    result = run_async(
        run_ops_agent(
            state(query, **identity),
            gateway(provider),
        )
    )

    assert result.tool.selected_tool == tool_name
    assert result.evidence.items
    assert result.task.status.value in {"RESOLVED", "TRANSFERRED"}
    assert provider.history[2].task is ModelTask.TOOL_SELECTION
    assert provider.history[3].task is ModelTask.TOOL_RESULT_REVIEW


def test_unseen_permission_and_incident_inputs_end_gracefully_with_clarification(
) -> None:
    provider = MockModelProvider(
        structured_responses=[
            understanding(
                primary_intent="ACCESS_ISSUE",
                entities={"user_id": "U-UNSEEN", "system_id": "UnknownSystem"},
            ),
            decision(),
            selection(
                "permission_query",
                {"user_id": "U-UNSEEN", "system_id": "UnknownSystem"},
            ),
            review(
                sufficient=False,
                summary="未找到该用户与系统组合的权限快照。",
                unresolved=["需要确认用户标识或系统名称"],
                action="ASK_USER",
            ),
            decision(
                "ASK_USER",
                goal="补充可查询的身份信息",
                rationale="当前只读结果不足以确认权限事实",
            ),
            grounded_response_plan(
                "ASK_USER",
                clarification_target="IDENTIFIER",
            ),
        ],
        responses=[],
    )

    result = run_async(
        run_ops_agent(
            state("我没有这个系统的菜单", user_id="U-UNSEEN"),
            gateway(provider),
        )
    )

    assert result.task.status.value == "WAITING_USER"
    assert result.response.is_final is False
    assert result.tool.last_result_status == "not_found"
    assert result.tool.evidence_sufficient is False
    assert result.facts.unresolved_questions


def test_privileged_write_selection_is_blocked_without_invoking_handler() -> None:
    calls: list[str] = []

    async def write_handler(
        request: WorkOrderQueryRequest,
    ) -> WorkOrderQueryResponse:
        calls.append(request.work_order_id)
        return WorkOrderQueryResponse(
            result_status=ToolResultStatus.FOUND,
            work_order_id=request.work_order_id,
        )

    registry = ToolRegistry(
        [
            RegisteredTool(
                spec=ToolSpec(
                    name="grant_admin",
                    description="Fixture write capability that must be blocked",
                    mode=ToolMode.WRITE,
                ),
                request_model=WorkOrderQueryRequest,
                response_model=WorkOrderQueryResponse,
                handler=write_handler,
            )
        ]
    )
    provider = MockModelProvider(
        structured_responses=[
            understanding(
                primary_intent="ACCESS_ISSUE",
                request_type="EXECUTE_CHANGE",
                risk_signal="PRIVILEGED_CHANGE",
                entities={"user_id": "U10023"},
            ),
            decision("SEARCH", goal="检查请求是否可由当前能力处理"),
            selection("grant_admin", {"work_order_id": "U10023"}),
            grounded_response_plan("TRANSFER_HUMAN"),
        ],
        responses=[],
    )

    result = run_async(
        run_ops_agent(
            state("帮我把U10023加成系统管理员。"),
            gateway(provider),
            registry,
        )
    )

    assert calls == []
    assert result.safety.blocked_reason == "READ_ONLY_POLICY_BLOCKED"
    assert result.handoff.required is True
    assert result.task.status.value == "TRANSFERRED"
    assert [item.task for item in provider.history] == [
        ModelTask.REQUEST_UNDERSTANDING,
        ModelTask.ACTION_DECISION,
        ModelTask.TOOL_SELECTION,
        ModelTask.HANDOFF_GENERATION,
    ]
    handoff_context = json.loads(provider.history[-1].messages[1].content)
    assert handoff_context["available_tools"][0]["name"] == "grant_admin"
    assert "available_tools" in provider.history[-1].messages[0].content


def test_unknown_tool_and_invalid_arguments_are_rejected_before_execution() -> None:
    for selection_payload in (
        selection("does_not_exist", {}),
        selection("work_order_query", {"not_work_order_id": "WO-1"}),
    ):
        provider = MockModelProvider(
            structured_responses=[
                understanding(),
                decision(),
                selection_payload,
                grounded_response_plan("TRANSFER_HUMAN"),
            ],
            responses=[],
        )
        result = run_async(
            run_ops_agent(state("请查询当前状态"), gateway(provider))
        )

        assert result.safety.blocked_reason == "TOOL_SELECTION_REJECTED"
        assert result.handoff.required is True
        assert len(provider.history) == 4


def test_tool_failure_is_reviewed_and_runtime_retry_limit_is_bounded() -> None:
    async def failing_handler(
        request: WorkOrderQueryRequest,
    ) -> WorkOrderQueryResponse:
        del request
        raise RuntimeError("adapter-private-secret")

    registry = ToolRegistry(
        [
            RegisteredTool(
                spec=ToolSpec(
                    name="failing_query",
                    description="Fixture failing read-only query",
                    mode=ToolMode.READ_ONLY,
                ),
                request_model=WorkOrderQueryRequest,
                response_model=WorkOrderQueryResponse,
                handler=failing_handler,
            )
        ]
    )
    provider = MockModelProvider(
        structured_responses=[
            understanding(),
            decision(),
            selection("failing_query", {"work_order_id": "WO-1"}),
            review(
                sufficient=False,
                summary="只读查询执行失败，当前没有可确认事实。",
                unresolved=["查询服务暂时不可用"],
                action="TRANSFER_HUMAN",
            ),
            decision(
                "TRANSFER_HUMAN",
                goal="转人工处理查询失败",
                rationale="模型判断当前没有可用证据",
            ),
            grounded_response_plan("TRANSFER_HUMAN"),
        ],
        responses=[],
    )
    initial = state("请查询工单")
    result = run_async(run_ops_agent(initial, gateway(provider), registry))

    assert result.tool.last_error_code == "TOOL_EXECUTION_FAILED"
    assert result.loop.retry_count == 1
    assert result.handoff.required is True
    assert "adapter-private-secret" not in result.model_dump_json()


def test_repeated_adapter_failures_stop_at_the_retry_limit() -> None:
    calls: list[str] = []

    async def failing_handler(
        request: WorkOrderQueryRequest,
    ) -> WorkOrderQueryResponse:
        calls.append(request.work_order_id)
        raise RuntimeError("adapter-private-secret")

    registry = ToolRegistry(
        [
            RegisteredTool(
                spec=ToolSpec(
                    name="retryable_query",
                    description="Fixture retryable read-only query",
                    mode=ToolMode.READ_ONLY,
                ),
                request_model=WorkOrderQueryRequest,
                response_model=WorkOrderQueryResponse,
                handler=failing_handler,
            )
        ]
    )
    provider = MockModelProvider(
        structured_responses=[
            understanding(),
            decision(),
            selection("retryable_query", {"work_order_id": "WO-1"}),
            review(
                sufficient=False,
                summary="第一次查询失败，没有可确认事实。",
                unresolved=["查询服务暂时不可用"],
                action="SEARCH",
            ),
            decision("SEARCH", goal="再次尝试查询", rationale="仍需确认事实"),
            selection("retryable_query", {"work_order_id": "WO-1"}),
            review(
                sufficient=False,
                summary="重试仍失败，没有可确认事实。",
                unresolved=["查询服务仍不可用"],
                action="TRANSFER_HUMAN",
            ),
            grounded_response_plan("TRANSFER_HUMAN"),
        ],
        responses=[],
    )

    result, events = run_async(
        run_ops_agent_with_trace(
            state("请查询工单"),
            gateway(provider),
            registry,
        )
    )

    assert calls == ["WO-1", "WO-1"]
    assert result.loop.retry_count == result.loop.max_retries == 2
    assert result.safety.blocked_reason == "RUNTIME_LIMIT_REACHED"
    assert result.handoff.required is True
    assert [event.node for event in events].count("decide_action") == 2
    assert "adapter-private-secret" not in result.model_dump_json()


def test_max_tool_call_limit_is_enforced_before_selection() -> None:
    provider = MockModelProvider(
        structured_responses=[
            understanding(),
            decision(),
            grounded_response_plan("TRANSFER_HUMAN"),
        ],
        responses=[],
    )
    initial = OpsAgentState(
        conversation={"current_query": "请查询工单"},
        loop={"tool_call_count": 1, "max_tool_calls": 1},
    )

    result, events = run_async(run_ops_agent_with_trace(initial, gateway(provider)))

    assert result.safety.blocked_reason == "RUNTIME_LIMIT_REACHED"
    assert result.handoff.required is True
    assert all(event.node != "select_tool" for event in events)
    assert provider.invocation_count == 3


def test_concurrent_runs_copy_registry_and_keep_canonical_states_isolated() -> None:
    registry = build_default_tool_registry()
    first_provider = MockModelProvider(
        structured_responses=[
            understanding(entities={"work_order_id": "WO20260001"}),
            decision(),
            selection("work_order_query", {"work_order_id": "WO20260001"}),
            review(sufficient=True, summary="已确认工单事实", facts=["等待 4 小时"]),
            decision("REPLY", goal="回复", rationale="证据足够"),
            grounded_response_plan("REPLY"),
        ],
        responses=[],
    )
    second_provider = MockModelProvider(
        structured_responses=[
            understanding(entities={"work_order_id": "WO-UNSEEN"}),
            decision(),
            selection("work_order_query", {"work_order_id": "WO-UNSEEN"}),
            review(
                sufficient=False,
                summary="未找到工单",
                unresolved=["需要确认工单号"],
                action="ASK_USER",
            ),
            decision("ASK_USER", goal="补充工单号", rationale="证据不足"),
            grounded_response_plan("ASK_USER", clarification_target="IDENTIFIER"),
        ],
        responses=[],
    )
    first_state = state("第一个请求")
    second_state = state("第二个请求")

    async def run_both() -> tuple[OpsAgentState, OpsAgentState]:
        return await asyncio.gather(
            run_ops_agent(first_state, gateway(first_provider), registry),
            run_ops_agent(second_state, gateway(second_provider), registry),
        )

    first, second = run_async(run_both())

    assert first.response.message == (
        "当前没有可引用的来源字段，无法基于只读证据给出事实回复。"
    )
    assert second.response.message == "请补充要查询的对象标识。"
    assert first_state.conversation.current_query == "第一个请求"
    assert second_state.conversation.current_query == "第二个请求"


def test_model_failure_at_new_selection_node_propagates_without_fallback() -> None:
    provider = MockModelProvider(
        structured_responses=[
            understanding(),
            decision(),
            ModelInvocationError("selection provider failed"),
        ]
    )

    with pytest.raises(ModelInvocationError):
        run_async(run_ops_agent(state("查询工单"), gateway(provider)))

    assert [item.task for item in provider.history] == [
        ModelTask.REQUEST_UNDERSTANDING,
        ModelTask.ACTION_DECISION,
        ModelTask.TOOL_SELECTION,
    ]
