"""Integration coverage for the real knowledge tool and Agent boundaries."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

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
from opsmind.evals import EvalSuiteLoader
from opsmind.knowledge.repository import LocalKnowledgeRepository
from opsmind.knowledge.retrieval import LexicalKnowledgeSearchService
from opsmind.knowledge.tool import knowledge_registration
from opsmind.models import MockModelProvider, ModelGateway, ModelProfile, ModelRoute
from opsmind.runs import SQLiteRunRepository
from opsmind.state import AgentAction, PrimaryIntent, RequestType, RiskSignal
from opsmind.tools import ToolRegistry, ToolResultStatus


def _knowledge_root(
    root: Path,
    *,
    content: str,
    source_file: str = "source.md",
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / source_file).write_text(content, encoding="utf-8")
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "corpus_id": "integration",
                "corpus_version": "1",
                "documents": [
                    {
                        "document_id": "KTEST",
                        "title": "集成测试手册",
                        "system_id": "TestSystem",
                        "document_type": "SOP",
                        "version": "1.0",
                        "updated_at": "2026-09-07",
                        "status": "ACTIVE",
                        "source_file": source_file,
                        "tags": ["synthetic"],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return root


def _runtime(
    responses: list[object],
    *,
    tool_registry: ToolRegistry | None = None,
) -> tuple[OpsAgentRuntime, MockModelProvider]:
    provider = MockModelProvider(structured_responses=responses, responses=[])
    gateway = ModelGateway(
        routes={
            ModelProfile.CHEAP: ModelRoute(
                profile=ModelProfile.CHEAP,
                provider="mock",
                model="integration-mock",
            )
        },
        providers={"mock": provider},
    )
    return OpsAgentRuntime(gateway, tool_registry=tool_registry), provider


def _knowledge_sequence(
    query: str,
    *,
    request_type: RequestType = RequestType.HOW_TO,
) -> list[object]:
    """Return one queued model turn that exercises every knowledge node."""

    return [
        RequestUnderstandingOutput(
            primary_intent=PrimaryIntent.SYSTEM_OPERATION,
            request_type=request_type,
            symptom="需要稳定操作流程",
            entities={"system_id": "EquipFlow"},
            risk_signal=RiskSignal.NONE,
            uncertainty=None,
        ),
        ActionDecisionOutput(
            action=AgentAction.SEARCH,
            goal="检索稳定知识",
            rationale="当前问题需要引用操作手册",
        ),
        ToolSelectionOutput(
            selected_tool="knowledge_search",
            arguments={"query": query},
            expected_resolution="获取一个版本化 SOP 片段",
        ),
        ToolResultReviewOutput(
            evidence_sufficient=True,
            summary="已取得版本化知识片段。",
            confirmed_facts=["来源片段已返回"],
            unresolved_questions=[],
            recommended_action=AgentAction.REPLY,
        ),
        ActionDecisionOutput(
            action=AgentAction.REPLY,
            goal="引用已检索的稳定知识",
            rationale="当前运行已有足够来源字段",
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


def _knowledge_registry(root: Path) -> ToolRegistry:
    service = LexicalKnowledgeSearchService(LocalKnowledgeRepository(root))
    return ToolRegistry([knowledge_registration(service)])


class _OfficialKnowledgeSubsetLoader(EvalSuiteLoader):
    """Run the shipped C01/C13 cases while keeping the test runtime small."""

    def load(self):
        suite = super().load()
        return suite.model_copy(
            update={
                "cases": [
                    case for case in suite.cases if case.case_id in {"C01", "C13"}
                ]
            }
        )


def test_registered_tool_returns_one_chunk_without_source_path_or_tail(
    tmp_path: Path,
) -> None:
    tail_sentinel = "UNSELECTED_DOCUMENT_TAIL_SENTINEL"
    root = _knowledge_root(
        tmp_path / "corpus",
        content="# 集成手册\nneedle 的操作说明。\n"
        + ("常规步骤。" * 260)
        + f"\n{tail_sentinel}",
        source_file="source.md",
    )
    registration = knowledge_registration(
        LexicalKnowledgeSearchService(LocalKnowledgeRepository(root))
    )
    registry = ToolRegistry([registration])

    result = __import__("asyncio").run(
        registry.execute("knowledge_search", {"query": "needle"})
    )

    assert result.output is not None
    assert result.output.result_status is ToolResultStatus.FOUND
    payload = result.output.model_dump(mode="json")
    assert payload["document_id"] == "KTEST"
    assert tail_sentinel not in json.dumps(payload, ensure_ascii=False)
    assert "source_file" not in payload
    assert "/private/internal/knowledge/source.md" not in json.dumps(
        payload, ensure_ascii=False
    )


def test_fastapi_chat_persists_real_knowledge_evidence_safely(
    tmp_path: Path,
) -> None:
    tail_sentinel = "UNSELECTED_DOCUMENT_TAIL_SENTINEL"
    root = _knowledge_root(
        tmp_path / "corpus",
        content="# 故障处理\nneedle 的关闭步骤。\n"
        + ("请完成验收。" * 260)
        + f"\n{tail_sentinel}",
        source_file="source.md",
    )
    responses = _knowledge_sequence("needle")
    runtime, provider = _runtime(
        responses,
        tool_registry=_knowledge_registry(root),
    )
    app = create_app(
        runtime=runtime,
        run_repository=SQLiteRunRepository(tmp_path / "opsmind.db"),
    )

    response = TestClient(app).post(
        "/api/v1/chat",
        json={"message": "needle 怎么操作？", "thread_id": "knowledge-thread"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"]
    assert body["final_reply"]
    assert body["evidence"][0]["source"] == "knowledge_search"
    assert body["evidence"][0]["key_fields"]["document_id"] == "KTEST"
    assert any(step["node"] == "execute_tool" for step in body["trace"])
    assert provider.invocation_count == 6
    assert tail_sentinel not in provider.history[3].messages[1].content
    assert tail_sentinel not in provider.history[5].messages[1].content
    public_text = response.text
    run_detail = TestClient(app).get(f"/api/v1/runs/{body['run_id']}")
    thread_detail = TestClient(app).get("/api/v1/threads/knowledge-thread")
    assert run_detail.status_code == thread_detail.status_code == 200
    assert tail_sentinel not in public_text
    assert tail_sentinel not in run_detail.text
    assert tail_sentinel not in thread_detail.text
    assert "/private/internal/knowledge/source.md" not in (
        public_text + run_detail.text + thread_detail.text
    )


def test_conversation_second_run_uses_fresh_knowledge_evidence(
    tmp_path: Path,
) -> None:
    first = _knowledge_sequence("故障工单应该怎么关闭？")
    second = _knowledge_sequence(
        "关闭前需要确认什么？",
        request_type=RequestType.CONTINUE_CASE,
    )
    runtime, provider = _runtime(first + second)
    app = create_app(
        runtime=runtime,
        run_repository=SQLiteRunRepository(tmp_path / "opsmind.db"),
    )
    client = TestClient(app)

    first_response = client.post(
        "/api/v1/chat",
        json={
            "message": "故障工单应该怎么关闭？",
            "thread_id": "continuity",
        },
    )
    second_response = client.post(
        "/api/v1/chat",
        json={
            "message": "关闭前需要确认什么？",
            "thread_id": "continuity",
        },
    )

    assert first_response.status_code == second_response.status_code == 200
    first_body = first_response.json()
    second_body = second_response.json()
    assert first_body["thread_id"] == second_body["thread_id"] == "continuity"
    assert first_body["request_id"] != second_body["request_id"]
    assert first_body["run_id"] != second_body["run_id"]
    assert second_body["understanding"]["request_type"] == "CONTINUE_CASE"
    assert second_body["evidence"][0]["source"] == "knowledge_search"
    assert second_body["evidence"][0]["evidence_id"] == "E1"
    assert second_body["evidence"][0]["timestamp"] != first_body["evidence"][0][
        "timestamp"
    ]
    assert provider.invocation_count == 12
    understanding_context = json.loads(provider.history[6].messages[1].content)
    assert understanding_context["current_query"] == "关闭前需要确认什么？"
    assert understanding_context["recent_turns"]
    assert "knowledge_search" not in json.dumps(
        understanding_context["important_entities"], ensure_ascii=False
    )


def test_eval_endpoint_uses_real_knowledge_runtime_for_two_cases(
    tmp_path: Path,
) -> None:
    responses = _knowledge_sequence("故障工单应该怎么关闭？")
    responses += _knowledge_sequence("设备台账怎么导出？")
    runtime, provider = _runtime(responses)
    app = create_app(
        runtime=runtime,
        run_repository=SQLiteRunRepository(tmp_path / "opsmind.db"),
        eval_suite_loader=_OfficialKnowledgeSubsetLoader(),
    )

    response = TestClient(app).post(
        "/api/v1/evals/run",
        json={"suite_id": "opsmind-golden"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["lifecycle_status"] == "COMPLETED"
    assert body["passed_count"] == 2
    assert [case["status"] for case in body["case_results"]] == ["PASS", "PASS"]
    assert len(body["case_runs"]) == 2
    assert provider.invocation_count == 12
