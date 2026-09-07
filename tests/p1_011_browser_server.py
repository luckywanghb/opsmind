"""Test-only FastAPI app used by the real browser acceptance run.

The frontend and FastAPI process are real; only the model provider is queued
and deterministic so the browser run does not require external credentials.
"""

from __future__ import annotations

import os
from pathlib import Path

from opsmind.agent.schemas import (
    ActionDecisionOutput,
    EvidenceReference,
    GroundedResponsePlanOutput,
    RequestUnderstandingOutput,
    ResponsePresentationIntent,
    ToolResultReviewOutput,
    ToolSelectionOutput,
)
from opsmind.api.app import create_app
from opsmind.api.runtime import OpsAgentRuntime
from opsmind.models import (
    MockModelProvider,
    ModelGateway,
    ModelProfile,
    ModelRoute,
)
from opsmind.runs import SQLiteRunRepository
from opsmind.state import AgentAction, PrimaryIntent, RequestType, RiskSignal


def _responses() -> list[object]:
    return [
        RequestUnderstandingOutput(
            primary_intent=PrimaryIntent.SYSTEM_OPERATION,
            request_type=RequestType.HOW_TO,
            symptom="需要故障工单关闭步骤",
            entities={"system_id": "EquipFlow"},
            risk_signal=RiskSignal.NONE,
            uncertainty=None,
        ),
        ActionDecisionOutput(
            action=AgentAction.SEARCH,
            goal="检索版本化 SOP",
            rationale="这是稳定的操作流程问题",
        ),
        ToolSelectionOutput(
            selected_tool="knowledge_search",
            arguments={"query": "故障工单应该怎么关闭？"},
            expected_resolution="获取故障工单关闭 SOP",
        ),
        ToolResultReviewOutput(
            evidence_sufficient=True,
            summary="已复核知识片段",
            confirmed_facts=["已取得 K001 文档片段"],
            unresolved_questions=[],
            recommended_action=AgentAction.REPLY,
        ),
        ActionDecisionOutput(
            action=AgentAction.REPLY,
            goal="基于当前知识证据回复",
            rationale="当前运行已有足够的 SOP 来源字段",
        ),
        GroundedResponsePlanOutput(
            terminal_mode="REPLY",
            presentation_intent=ResponsePresentationIntent.FACTS,
            evidence_references=[
                EvidenceReference(evidence_id="E1", path="document_id"),
                EvidenceReference(evidence_id="E1", path="title"),
                EvidenceReference(evidence_id="E1", path="excerpt"),
            ],
            limitation="NONE",
            clarification_target="GENERIC",
        ),
    ]


_provider = MockModelProvider(structured_responses=_responses())
_gateway = ModelGateway(
    routes={
        ModelProfile.CHEAP: ModelRoute(
            profile=ModelProfile.CHEAP,
            provider="browser-mock",
            model="browser-deterministic-mock",
        )
    },
    providers={"browser-mock": _provider},
)
_runtime = OpsAgentRuntime(_gateway)
_store = Path(
    os.environ.get(
        "OPSMIND_BROWSER_RUN_STORE",
        "/tmp/opsmind-p1-011-browser.db",
    )
)
app = create_app(
    runtime=_runtime,
    run_repository=SQLiteRunRepository(_store),
)
