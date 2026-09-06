"""Real execution-boundary multi-run conversation acceptance tests."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from opsmind.agent.schemas import ActionDecisionOutput, RequestUnderstandingOutput
from opsmind.api.app import create_app
from opsmind.api.runtime import OpsAgentRuntime
from opsmind.api.settings import RuntimeSettings
from opsmind.conversations import (
    ConversationCheckpoint,
    ConversationLease,
    ConversationPersistenceError,
    ConversationStatus,
    SQLiteConversationRepository,
)
from opsmind.evals import EvalSuiteLoader
from opsmind.models import (
    MockModelProvider,
    ModelGateway,
    ModelProfile,
    ModelRoute,
    ModelStructuredOutputError,
)
from opsmind.state import (
    AgentAction,
    PrimaryIntent,
    RequestType,
    ResolutionStatus,
    RiskSignal,
)


def _understanding(
    request_type: RequestType,
    *,
    entities: dict[str, object] | None = None,
) -> RequestUnderstandingOutput:
    return RequestUnderstandingOutput(
        primary_intent=PrimaryIntent.WORKFLOW_ISSUE,
        request_type=request_type,
        symptom="work order handling status",
        entities=entities or {},
        risk_signal=RiskSignal.NONE,
        uncertainty=None,
    )


def _decision(action: AgentAction) -> ActionDecisionOutput:
    return ActionDecisionOutput(
        action=action,
        goal="continue the current work-order task",
        rationale="use current-run evidence when a current fact is requested",
    )


def _selection() -> dict[str, object]:
    return {
        "selected_tool": "work_order_query",
        "arguments": {"work_order_id": "WO20260001"},
        "expected_resolution": "obtain current work-order state",
    }


def _review() -> dict[str, object]:
    return {
        "evidence_sufficient": True,
        "summary": "current work-order state reviewed",
        "confirmed_facts": ["current handler confirmed from this run"],
        "unresolved_questions": [],
        "recommended_action": "REPLY",
    }


def _reply_plan() -> dict[str, object]:
    return {
        "terminal_mode": "REPLY",
        "presentation_intent": "FACTS",
        "evidence_references": [
            {"evidence_id": "E1", "path": "key_fields.current_handler"}
        ],
        "limitation": "NONE",
        "clarification_target": "GENERIC",
    }


def _clarification_plan() -> dict[str, object]:
    return {
        "terminal_mode": "ASK_USER",
        "presentation_intent": "CLARIFICATION",
        "evidence_references": [],
        "limitation": "NONE",
        "clarification_target": "IDENTIFIER",
    }


def _client(
    tmp_path: Path, responses: list[object]
) -> tuple[TestClient, MockModelProvider]:
    provider = MockModelProvider(structured_responses=responses, responses=[])
    runtime = OpsAgentRuntime(
        ModelGateway(
            routes={
                ModelProfile.CHEAP: ModelRoute(
                    profile=ModelProfile.CHEAP,
                    provider="mock",
                    model="conversation-test",
                )
            },
            providers={"mock": provider},
        )
    )
    app = create_app(
        runtime=runtime,
        settings=RuntimeSettings(run_store_path=tmp_path / "opsmind.db"),
    )
    return TestClient(app), provider


def _search_reply_responses(request_type: RequestType) -> list[object]:
    return [
        _understanding(
            request_type,
            entities={"work_order_id": "WO20260001"},
        ),
        _decision(AgentAction.SEARCH),
        _selection(),
        _review(),
        _decision(AgentAction.REPLY),
        _reply_plan(),
    ]


def test_same_thread_restores_entity_but_reacquires_current_evidence(
    tmp_path: Path,
) -> None:
    responses = _search_reply_responses(RequestType.DIAGNOSE)
    responses.extend(_search_reply_responses(RequestType.CONTINUE_CASE))
    client, provider = _client(tmp_path, responses)

    first = client.post(
        "/api/v1/chat",
        json={
            "message": "WO20260001为什么一直没处理？",
            "source_context": {"user_id": "U10023"},
        },
    )
    assert first.status_code == 200
    first_body = first.json()
    second = client.post(
        "/api/v1/chat",
        json={
            "message": "那现在是谁在处理？",
            "thread_id": first_body["thread_id"],
            "source_context": {"user_id": "U10023"},
        },
    )

    assert second.status_code == 200
    second_body = second.json()
    assert second_body["thread_id"] == first_body["thread_id"]
    assert second_body["run_id"] != first_body["run_id"]
    assert second_body["request_id"] != first_body["request_id"]
    assert second_body["understanding"]["request_type"] == "CONTINUE_CASE"
    assert second_body["final_reply"] == "来源 work_order_query：当前处理人=U10108"
    assert [
        item["summary"]
        for item in second_body["trace"]
        if item["node"] == "execute_tool"
    ] == ["work_order_query: found"]

    second_understanding_context = json.loads(
        provider.history[6].messages[1].content
    )
    assert second_understanding_context["current_query"] == "那现在是谁在处理？"
    assert second_understanding_context["original_query"] == (
        "WO20260001为什么一直没处理？"
    )
    assert second_understanding_context["important_entities"] == {
        "work_order_id": "WO20260001"
    }
    assert len(second_understanding_context["recent_turns"]) == 2
    second_selection_context = json.loads(provider.history[8].messages[1].content)
    assert second_selection_context["understanding"]["entities"] == {
        "work_order_id": "WO20260001"
    }


def test_ask_user_answer_restores_clarification_and_original_problem(
    tmp_path: Path,
) -> None:
    responses: list[object] = [
        _understanding(RequestType.DIAGNOSE),
        _decision(AgentAction.ASK_USER),
        _clarification_plan(),
    ]
    responses.extend(_search_reply_responses(RequestType.CONTINUE_CASE))
    client, provider = _client(tmp_path, responses)

    first = client.post(
        "/api/v1/chat",
        json={"message": "帮我看看这个工单为什么没人处理", "thread_id": "ask-thread"},
    )
    assert first.status_code == 200
    assert first.json()["status"] == "waiting_user"
    assert first.json()["final_reply"] == "请补充要查询的对象标识。"
    second = client.post(
        "/api/v1/chat",
        json={"message": "WO20260001", "thread_id": "ask-thread"},
    )

    assert second.status_code == 200
    assert second.json()["understanding"]["request_type"] == "CONTINUE_CASE"
    context = json.loads(provider.history[3].messages[1].content)
    assert context["original_query"] == "帮我看看这个工单为什么没人处理"
    assert context["last_assistant_message"] == "请补充要查询的对象标识。"
    assert context["recent_turns"][-1]["role"] == "ASSISTANT"


def test_thread_read_api_and_cross_thread_isolation(tmp_path: Path) -> None:
    responses = [
        _understanding(RequestType.OTHER),
        _decision(AgentAction.END_CONVERSATION),
        _understanding(RequestType.OTHER),
        _decision(AgentAction.END_CONVERSATION),
    ]
    client, provider = _client(tmp_path, responses)
    first = client.post(
        "/api/v1/chat",
        json={"message": "WO20260001", "thread_id": "thread-A"},
    )
    second = client.post(
        "/api/v1/chat",
        json={"message": "independent", "thread_id": "thread-B"},
    )
    assert first.status_code == second.status_code == 200

    context_b = json.loads(provider.history[2].messages[1].content)
    assert context_b["original_query"] == "independent"
    assert context_b["recent_turns"] == []
    assert "WO20260001" not in json.dumps(context_b)

    listed = client.get("/api/v1/threads?limit=50")
    assert listed.status_code == 200
    assert {item["thread_id"] for item in listed.json()} == {
        "thread-A",
        "thread-B",
    }
    detail = client.get("/api/v1/threads/thread-A")
    assert detail.status_code == 200
    assert detail.json()["thread"]["latest_run_id"] == first.json()["run_id"]
    assert detail.json()["turns"][0]["request_id"] == first.json()["request_id"]
    assert client.get("/api/v1/threads/missing").status_code == 404


def test_conversation_store_excludes_arbitrary_context_and_control_payloads(
    tmp_path: Path,
) -> None:
    client, _ = _client(
        tmp_path,
        [
            _understanding(RequestType.OTHER),
            ActionDecisionOutput(
                action=AgentAction.END_CONVERSATION,
                goal="PROMPT_SECRET_SENTINEL",
                rationale="PROVIDER_PAYLOAD_SENTINEL CHAIN_OF_THOUGHT_SENTINEL",
            ),
        ],
    )
    response = client.post(
        "/api/v1/chat",
        json={
            "message": "safe user message",
            "thread_id": "safe-thread",
            "source_context": {
                "arbitrary": "ARBITRARY_SOURCE_CONTEXT_SENTINEL",
                "authorization": "credentials",
            },
        },
    )
    assert response.status_code == 200

    connection = sqlite3.connect(tmp_path / "opsmind.db")
    try:
        values: list[str] = []
        for table in (
            "conversation_threads",
            "conversation_turns",
            "conversation_checkpoints",
        ):
            for row in connection.execute(f"SELECT * FROM {table}"):
                values.extend(str(value) for value in row if value is not None)
    finally:
        connection.close()
    stored = " ".join(values)
    for sentinel in (
        "PROMPT_SECRET_SENTINEL",
        "PROVIDER_PAYLOAD_SENTINEL",
        "CHAIN_OF_THOUGHT_SENTINEL",
        "ARBITRARY_SOURCE_CONTEXT_SENTINEL",
        "credentials",
    ):
        assert sentinel not in stored
    assert "safe user message" in stored


def test_different_explicit_user_cannot_load_thread_context(tmp_path: Path) -> None:
    client, provider = _client(
        tmp_path,
        [
            _understanding(RequestType.OTHER),
            _decision(AgentAction.END_CONVERSATION),
        ],
    )
    first = client.post(
        "/api/v1/chat",
        json={
            "message": "private",
            "thread_id": "identity-thread",
            "source_context": {"user_id": "U-A"},
        },
    )
    assert first.status_code == 200
    conflict = client.post(
        "/api/v1/chat",
        json={
            "message": "continue",
            "thread_id": "identity-thread",
            "source_context": {"user_id": "U-B"},
        },
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "CONVERSATION_IDENTITY_CONFLICT"
    assert provider.invocation_count == 2


def test_oversized_site_identity_fails_without_lossy_persistence(
    tmp_path: Path,
) -> None:
    client, provider = _client(tmp_path, [])

    response = client.post(
        "/api/v1/chat",
        json={
            "message": "initial",
            "thread_id": "oversized-site",
            "source_context": {"user_id": "U1", "site_id": "S" * 513},
        },
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "CONVERSATION_PERSISTENCE_UNAVAILABLE"
    assert provider.invocation_count == 0
    assert client.get("/api/v1/runs").json()[0]["lifecycle_status"] == "FAILED"
    assert client.get("/api/v1/threads").json() == []


class _TerminalFailureRepository(SQLiteConversationRepository):
    def complete_run(
        self,
        lease: ConversationLease,
        *,
        assistant_content: str | None,
        checkpoint: ConversationCheckpoint,
        status: ConversationStatus,
        previous_resolution_status: ResolutionStatus,
    ):
        del lease, assistant_content, checkpoint, status, previous_resolution_status
        raise ConversationPersistenceError("TRACEBACK_SECRET_SENTINEL /tmp/private.db")


def test_terminal_persistence_failure_is_safe_503_and_not_fake_success(
    tmp_path: Path,
) -> None:
    path = tmp_path / "opsmind.db"
    provider = MockModelProvider(
        structured_responses=[
            _understanding(RequestType.OTHER),
            _decision(AgentAction.END_CONVERSATION),
        ],
        responses=[],
    )
    runtime = OpsAgentRuntime(
        ModelGateway(
            routes={
                ModelProfile.CHEAP: ModelRoute(
                    profile=ModelProfile.CHEAP,
                    provider="mock",
                    model="conversation-test",
                )
            },
            providers={"mock": provider},
        )
    )
    repository = _TerminalFailureRepository(path)
    client = TestClient(
        create_app(
            runtime=runtime,
            settings=RuntimeSettings(run_store_path=path),
            conversation_repository=repository,
        ),
        raise_server_exceptions=False,
    )

    response = client.post(
        "/api/v1/chat",
        json={"message": "safe", "thread_id": "failure-thread"},
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == (
        "CONVERSATION_PERSISTENCE_UNAVAILABLE"
    )
    serialized = response.text
    assert "TRACEBACK_SECRET_SENTINEL" not in serialized
    assert "/tmp/private.db" not in serialized
    detail = repository.get("failure-thread")
    assert detail is not None
    assert [turn.role.value for turn in detail.turns] == ["USER"]
    assert detail.checkpoint is None


def test_failed_agent_run_keeps_only_user_turn_and_does_not_advance_checkpoint(
    tmp_path: Path,
) -> None:
    path = tmp_path / "opsmind.db"
    client, _ = _client(
        tmp_path,
        [ModelStructuredOutputError("TRACEBACK_SECRET_SENTINEL")],
    )

    response = client.post(
        "/api/v1/chat",
        json={"message": "failing input", "thread_id": "failed-thread"},
    )
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "MODEL_STRUCTURED_OUTPUT_INVALID"

    connection = sqlite3.connect(path)
    try:
        roles = connection.execute(
            """SELECT role FROM conversation_turns
               WHERE thread_id = 'failed-thread' ORDER BY sequence"""
        ).fetchall()
        checkpoint_count = connection.execute(
            """SELECT count(*) FROM conversation_checkpoints
               WHERE thread_id = 'failed-thread'"""
        ).fetchone()
    finally:
        connection.close()
    assert roles == [("USER",)]
    assert checkpoint_count == (0,)


def test_eval_c12_uses_real_conversation_path_and_resolves_known_gap(
    tmp_path: Path,
) -> None:
    suite_path = tmp_path / "c12.json"
    suite_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "suite_id": "c12-suite",
                "suite_version": "0.2",
                "description": "conversation continuity acceptance",
                "cases": [
                    {
                        "case_id": "C12",
                        "title": "continuation",
                        "turns": [
                            {"message": "WO20260001为什么一直没处理？"},
                            {"message": "那现在是谁在处理？"},
                        ],
                        "source_context": {"channel": "eval"},
                        "assertions": [
                            {
                                "assertion_id": "identity",
                                "type": "same_thread_across_turns",
                                "expected": True,
                            },
                            {
                                "assertion_id": "continuation",
                                "type": "request_type_in",
                                "expected": ["CONTINUE_CASE"],
                                "turn_index": 1,
                            },
                            {
                                "assertion_id": "tool",
                                "type": "required_tool_used",
                                "expected": ["work_order_query"],
                                "turn_index": 1,
                            },
                            {
                                "assertion_id": "argument",
                                "type": "tool_argument_equals",
                                "expected": {
                                    "tool": "work_order_query",
                                    "field": "work_order_id",
                                    "value": "WO20260001",
                                },
                                "turn_index": 1,
                            },
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    responses = _search_reply_responses(RequestType.DIAGNOSE)
    responses.extend(_search_reply_responses(RequestType.CONTINUE_CASE))
    provider = MockModelProvider(structured_responses=responses, responses=[])
    runtime = OpsAgentRuntime(
        ModelGateway(
            routes={
                ModelProfile.CHEAP: ModelRoute(
                    profile=ModelProfile.CHEAP,
                    provider="mock",
                    model="conversation-test",
                )
            },
            providers={"mock": provider},
        )
    )
    app = create_app(
        runtime=runtime,
        settings=RuntimeSettings(run_store_path=tmp_path / "opsmind.db"),
        eval_suite_loader=EvalSuiteLoader(suite_path),
    )

    response = TestClient(app).post(
        "/api/v1/evals/run", json={"suite_id": "c12-suite"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["suite_version"] == "0.2"
    assert body["case_results"][0]["status"] == "PASS"
    assert body["case_results"][0]["known_gap"] is None
    assert len(body["case_results"][0]["run_ids"]) == 2
    second_context = json.loads(provider.history[6].messages[1].content)
    assert second_context["important_entities"]["work_order_id"] == "WO20260001"
