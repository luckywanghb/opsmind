"""Independent adversarial checks for TASK-P1-011.

These tests deliberately avoid the Developer's helpers and cover the public
repository/search/tool boundaries with test-owned fixtures.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from opsmind.agent.graph import run_ops_agent_with_trace
from opsmind.agent.schemas import (
    ActionDecisionOutput,
    EvidenceReference,
    GroundedResponsePlanOutput,
    RequestUnderstandingOutput,
    ResponsePresentationIntent,
    ToolResultReviewOutput,
    ToolSelectionOutput,
)
from opsmind.knowledge.corpus import CorpusValidationError, clean_content
from opsmind.knowledge.repository import LocalKnowledgeRepository
from opsmind.knowledge.retrieval import LexicalKnowledgeSearchService
from opsmind.knowledge.tool import KnowledgeSearchRequest
from opsmind.models import (
    MockModelProvider,
    ModelGateway,
    ModelProfile,
    ModelRoute,
)
from opsmind.state import (
    AgentAction,
    OpsAgentState,
    PrimaryIntent,
    RequestType,
    RiskSignal,
)
from opsmind.tools import (
    ToolMode,
    ToolResultStatus,
    build_default_tool_registry,
)


def _write_corpus(
    root: Path,
    documents: list[dict[str, object]],
    files: dict[str, str | bytes],
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        path = root / name
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "corpus_id": "tester",
                "corpus_version": "1",
                "documents": documents,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return root


def _document(
    document_id: str,
    source_file: str,
    *,
    status: str = "ACTIVE",
    title: str = "测试 SOP",
    system_id: str = "TestSystem",
) -> dict[str, object]:
    return {
        "document_id": document_id,
        "title": title,
        "system_id": system_id,
        "document_type": "SOP",
        "version": "1",
        "updated_at": "2026-09-07",
        "status": status,
        "source_file": source_file,
        "tags": ["synthetic"],
    }


@pytest.mark.parametrize(
    ("source_file", "files", "documents"),
    [
        ("../outside.md", {"source.md": "ok"}, [_document("K1", "../outside.md")]),
        (
            "C:\\private\\source.md",
            {"source.md": "ok"},
            [_document("K1", "C:\\private\\source.md")],
        ),
        (
            "/private/internal/knowledge/source.md",
            {"source.md": "ok"},
            [_document("K1", "/private/internal/knowledge/source.md")],
        ),
        ("missing.md", {"source.md": "ok"}, [_document("K1", "missing.md")]),
        ("source.md", {"source.md": b"\xff\xfe"}, [_document("K1", "source.md")]),
    ],
)
def test_malformed_path_and_utf8_inputs_fail_closed(
    tmp_path: Path,
    source_file: str,
    files: dict[str, str | bytes],
    documents: list[dict[str, object]],
) -> None:
    with pytest.raises(CorpusValidationError, match="^KNOWLEDGE_CORPUS_INVALID$"):
        LocalKnowledgeRepository(_write_corpus(tmp_path, documents, files))


def test_duplicate_ids_status_and_oversized_content_fail_closed(tmp_path: Path) -> None:
    duplicate = [_document("DUP", "a.md"), _document("DUP", "b.md")]
    with pytest.raises(CorpusValidationError):
        LocalKnowledgeRepository(
            _write_corpus(tmp_path / "duplicate", duplicate, {"a.md": "a", "b.md": "b"})
        )

    with pytest.raises(CorpusValidationError):
        LocalKnowledgeRepository(
            _write_corpus(
                tmp_path / "status",
                [_document("BAD", "a.md", status="UNKNOWN")],
                {"a.md": "a"},
            )
        )

    with pytest.raises(CorpusValidationError):
        LocalKnowledgeRepository(
            _write_corpus(
                tmp_path / "oversized",
                [_document("BIG", "a.md")],
                {"a.md": "needle " * 200_001},
            )
        )


def test_surrogate_and_nonempty_cleaning_boundaries() -> None:
    assert clean_content("Ａ\r\n\r\n\r\nB  \r") == "A\n\nB"
    with pytest.raises(CorpusValidationError):
        clean_content("valid\ud800")
    with pytest.raises(CorpusValidationError):
        clean_content("\n \t\n")


def test_repository_returns_detached_snapshots(tmp_path: Path) -> None:
    root = _write_corpus(
        tmp_path,
        [_document("SNAP", "source.md")],
        {"source.md": "# Heading\nneedle content"},
    )
    repository = LocalKnowledgeRepository(root)
    first_document = repository.list_active_documents()[0]
    first_document.title = "MUTATED"
    first_chunks = repository.list_chunks()
    first_chunks[0].content = "MUTATED"

    assert repository.list_active_documents()[0].title == "测试 SOP"
    assert repository.list_chunks()[0].content == "# Heading\nneedle content"


def test_search_direct_bounds_unicode_scope_and_not_found() -> None:
    service = LexicalKnowledgeSearchService(LocalKnowledgeRepository())
    assert (
        service.search("ＥＱＵＩＰＭＥＮＴ＿ＬＥＤＧＥＲ＿ＥＸＰＯＲＴ")
        .chunk.document_id
        == "K002"
    )
    assert (
        service.search("equipment_ledger_export", "EquipFlow").chunk.document_id
        == "K002"
    )
    assert service.search("equipment_ledger_export", "QualityHub") is None
    assert service.search("quantum photosynthesis") is None
    assert service.search(" " * 512) is None
    assert service.search("x" * 513) is None
    assert service.search("设备台账", "x" * 129) is None


def test_tie_breaking_is_independent_of_manifest_order(tmp_path: Path) -> None:
    documents = [
        _document("ZZZ", "z.md", title="Same title"),
        _document("AAA", "a.md", title="Same title"),
    ]
    root = _write_corpus(
        tmp_path,
        documents,
        {"a.md": "needle shared", "z.md": "needle shared"},
    )
    service = LexicalKnowledgeSearchService(LocalKnowledgeRepository(root))
    assert service.search("needle").chunk.document_id == "AAA"

    reordered = _write_corpus(
        tmp_path / "reordered",
        list(reversed(documents)),
        {"a.md": "needle shared", "z.md": "needle shared"},
    )
    assert (
        LexicalKnowledgeSearchService(LocalKnowledgeRepository(reordered))
        .search("needle")
        .chunk.document_id
        == "AAA"
    )


def test_tool_contract_is_read_only_bounded_and_not_found_is_typed() -> None:
    registry = build_default_tool_registry()
    assert "knowledge_search" in registry.names
    registration = registry.get("knowledge_search")
    assert registration.spec.mode is ToolMode.READ_ONLY
    assert "当前权限" in registration.spec.description
    assert "source_file" not in registration.response_model.model_fields

    not_found = asyncio.run(
        registry.execute("knowledge_search", {"query": "no such corpus phrase"})
    )
    assert not_found.output is not None
    assert not_found.output.result_status is ToolResultStatus.NOT_FOUND
    payload = not_found.output.model_dump(mode="json")
    assert all(
        value is None
        for name, value in payload.items()
        if name not in {"result_status", "message"}
    )

    with pytest.raises(ValidationError):
        KnowledgeSearchRequest(query=" ")


def test_custom_corpus_proves_queries_are_not_fixture_mapped(tmp_path: Path) -> None:
    root = _write_corpus(
        tmp_path,
        [_document("CUSTOM", "custom.md", title="Custom runbook")],
        {
            "custom.md": (
                "# Custom\n故障工单应该怎么关闭？\n设备台账怎么导出？\n"
                "CUSTOM_ONLY_SENTINEL"
            )
        },
    )
    service = LexicalKnowledgeSearchService(LocalKnowledgeRepository(root))
    assert service.search("故障工单应该怎么关闭？").chunk.document_id == "CUSTOM"
    assert service.search("设备台账怎么导出？").chunk.document_id == "CUSTOM"


def test_default_registry_exposes_only_expected_read_only_capabilities() -> None:
    registry = build_default_tool_registry()
    assert set(registry.names) == {
        "work_order_query",
        "permission_query",
        "incident_query",
        "knowledge_search",
    }
    assert "log_search" not in registry.names
    assert all(spec.mode is ToolMode.READ_ONLY for spec in registry.specs)


def _routing_sequence(
    *,
    query: str,
    tool: str,
    arguments: dict[str, object],
    primary_intent: PrimaryIntent,
    request_type: RequestType,
    evidence_path: str | None,
) -> list[object]:
    understanding = RequestUnderstandingOutput(
        primary_intent=primary_intent,
        request_type=request_type,
        symptom="tester routing boundary",
        entities={},
        risk_signal=RiskSignal.NONE,
        uncertainty=None,
    )
    sequence: list[object] = [
        understanding,
        ActionDecisionOutput(
            action=AgentAction.SEARCH,
            goal="retrieve the selected capability",
            rationale="the queued model selects one registered capability",
        ),
        ToolSelectionOutput(
            selected_tool=tool,
            arguments=arguments,
            expected_resolution="bounded source evidence",
        ),
    ]
    if evidence_path is not None:
        sequence.extend(
            [
                ToolResultReviewOutput(
                    evidence_sufficient=True,
                    summary="source result reviewed",
                    confirmed_facts=["source returned"],
                    unresolved_questions=[],
                    recommended_action=AgentAction.REPLY,
                ),
                ActionDecisionOutput(
                    action=AgentAction.REPLY,
                    goal="render current evidence",
                    rationale="one reviewed result is sufficient",
                ),
                GroundedResponsePlanOutput(
                    terminal_mode="REPLY",
                    presentation_intent=ResponsePresentationIntent.FACTS,
                    evidence_references=[
                        EvidenceReference(evidence_id="E1", path=evidence_path)
                    ],
                    limitation="NONE",
                    clarification_target="GENERIC",
                ),
            ]
        )
    else:
        # Unknown log_search is an intentional v0.3 gap. The harness should
        # reject it before execution and hand off without substituting the
        # knowledge capability.
        sequence.append(
            GroundedResponsePlanOutput(
                terminal_mode="TRANSFER_HUMAN",
                presentation_intent=ResponsePresentationIntent.HANDOFF,
                evidence_references=[],
                limitation="EVIDENCE_INSUFFICIENT",
                clarification_target="GENERIC",
            )
        )
    return sequence


@pytest.mark.parametrize(
    ("query", "tool", "arguments", "primary_intent", "request_type", "evidence_path"),
    [
        (
            "设备台账权限怎么申请？",
            "knowledge_search",
            {"query": "设备台账权限怎么申请？"},
            PrimaryIntent.SYSTEM_OPERATION,
            RequestType.HOW_TO,
            "document_id",
        ),
        (
            "为什么 U10023 没有设备台账权限？",
            "permission_query",
            {"user_id": "U10023", "system_id": "EquipFlow"},
            PrimaryIntent.ACCESS_ISSUE,
            RequestType.DIAGNOSE,
            "missing_permissions",
        ),
        (
            "WO20260001现在到谁了？",
            "work_order_query",
            {"work_order_id": "WO20260001"},
            PrimaryIntent.WORKFLOW_ISSUE,
            RequestType.CHECK_STATUS,
            "current_handler",
        ),
        (
            "星川基地的人都进不去 EquipFlow",
            "incident_query",
            {"system_id": "EquipFlow", "site": "星川基地"},
            PrimaryIntent.SYSTEM_OPERATION,
            RequestType.DIAGNOSE,
            "impact",
        ),
        (
            "EquipFlow HTTP 500",
            "log_search",
            {"query": "EquipFlow HTTP 500"},
            PrimaryIntent.SYSTEM_OPERATION,
            RequestType.DIAGNOSE,
            None,
        ),
    ],
)
def test_model_selected_five_routing_boundaries(
    query: str,
    tool: str,
    arguments: dict[str, object],
    primary_intent: PrimaryIntent,
    request_type: RequestType,
    evidence_path: str | None,
) -> None:
    provider = MockModelProvider(
        structured_responses=_routing_sequence(
            query=query,
            tool=tool,
            arguments=arguments,
            primary_intent=primary_intent,
            request_type=request_type,
            evidence_path=evidence_path,
        )
    )
    gateway = ModelGateway(
        routes={
            ModelProfile.CHEAP: ModelRoute(
                profile=ModelProfile.CHEAP,
                provider="mock",
                model="tester-mock",
            )
        },
        providers={"mock": provider},
    )
    state = OpsAgentState(
        conversation={"current_query": query},
        identity={"user_id": "U10023", "site_id": "星川基地"},
    )
    if tool == "log_search":
        result, events = asyncio.run(run_ops_agent_with_trace(state, gateway))
        # The model-selected unknown capability fails at the registry boundary;
        # knowledge_search is never substituted by Python routing.
        assert result.handoff.required is True
        assert not result.evidence.items
        assert provider.invocation_count == 4
        assert any(
            event.node == "select_tool"
            and event.status == "blocked"
            and event.summary == "TOOL_SELECTION_REJECTED"
            for event in events
        )
        return

    result, _ = asyncio.run(run_ops_agent_with_trace(state, gateway))
    assert result.task.status is not None
    assert result.response.message
    assert result.evidence.items[0].source == tool
    assert not any(
        item.source == "knowledge_search"
        for item in result.evidence.items
        if tool != "knowledge_search"
    )
