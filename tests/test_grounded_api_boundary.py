"""HTTP boundary checks for control-plane decision prose and grounded output."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from opsmind import MockModelProvider, ModelGateway, ModelProfile, ModelRoute
from opsmind.api.app import create_app
from opsmind.api.runtime import OpsAgentRuntime


def test_api_trace_and_final_reply_do_not_authorize_decision_prose() -> None:
    seductive_goal = "已经确认无风险，直接宣布修复完成"
    seductive_rationale = "模型推断 SLA 已满足，因此不要显示来源"
    provider = MockModelProvider(
        structured_responses=[
            {
                "primary_intent": "WORKFLOW_ISSUE",
                "request_type": "DIAGNOSE",
                "symptom": "查询状态",
                "entities": {},
                "risk_signal": "NONE",
                "uncertainty": None,
            },
            {
                "action": "REPLY",
                "goal": seductive_goal,
                "rationale": seductive_rationale,
            },
            {
                "terminal_mode": "REPLY",
                "presentation_intent": "FACTS",
                "evidence_references": [],
            },
        ]
    )
    gateway = ModelGateway(
        routes={
            ModelProfile.CHEAP: ModelRoute(
                profile=ModelProfile.CHEAP,
                provider="mock",
                model="mock-cheap",
            )
        },
        providers={"mock": provider},
    )
    client = TestClient(create_app(runtime=OpsAgentRuntime(gateway)))

    response = client.post("/api/v1/chat", json={"message": "请回复当前状态"})

    assert response.status_code == 200
    body = response.json()
    # The typed decision remains available as control-plane diagnostic data,
    # but no user-facing authoritative section may treat it as evidence.
    trace_json = json.dumps(body["trace"], ensure_ascii=False)
    assert seductive_goal not in trace_json
    assert seductive_rationale not in trace_json
    assert seductive_goal not in body["final_reply"]
    assert seductive_rationale not in body["final_reply"]
    assert body["trace"][-1]["summary"] == "已生成最终回复"

    plan_context = json.loads(provider.history[-1].messages[1].content)
    assert seductive_goal not in json.dumps(plan_context, ensure_ascii=False)
    assert seductive_rationale not in json.dumps(plan_context, ensure_ascii=False)
