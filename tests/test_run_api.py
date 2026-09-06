"""Integration and leakage tests for persisted Agent runs."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import TypeVar

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from opsmind.agent.schemas import (
    ActionDecisionOutput,
    GroundedResponsePlanOutput,
    RequestUnderstandingOutput,
    ToolResultReviewOutput,
    ToolSelectionOutput,
)
from opsmind.api.app import create_app
from opsmind.api.runtime import OpsAgentRuntime
from opsmind.api.settings import RuntimeSettings
from opsmind.models import (
    MockModelProvider,
    ModelGateway,
    ModelInvocationError,
    ModelProfile,
    ModelResponse,
    ModelRoute,
    ModelStructuredOutputError,
    StructuredModelResponse,
)
from opsmind.runs import (
    AgentRun,
    RunLifecycleStatus,
    RunPersistenceError,
    SQLiteRunRepository,
)
from opsmind.state import (
    AgentAction,
    PrimaryIntent,
    RequestType,
    RiskSignal,
)
from opsmind.tools import (
    RegisteredTool,
    ToolMode,
    ToolRegistry,
    ToolSpec,
    WorkOrderQueryRequest,
    WorkOrderQueryResponse,
)
from opsmind.tools.contracts import ToolResultStatus

T = TypeVar("T", bound=BaseModel)


def _understanding() -> RequestUnderstandingOutput:
    return RequestUnderstandingOutput(
        primary_intent=PrimaryIntent.WORKFLOW_ISSUE,
        request_type=RequestType.DIAGNOSE,
        symptom="work order waiting",
        entities={"work_order_id": "WO20260001"},
        risk_signal=RiskSignal.NONE,
        uncertainty=None,
    )


def _decision(action: AgentAction) -> ActionDecisionOutput:
    return ActionDecisionOutput(
        action=action,
        goal=f"goal:{action.value}",
        rationale=f"rationale:{action.value}",
    )


def _plan(
    action: AgentAction,
    *,
    with_status_reference: bool = False,
) -> dict[str, object]:
    intent = {
        AgentAction.REPLY: "FACTS",
        AgentAction.ASK_USER: "CLARIFICATION",
        AgentAction.TRANSFER_HUMAN: "HANDOFF",
        AgentAction.END_CONVERSATION: "CLOSE",
    }[action]
    return {
        "terminal_mode": action.value,
        "presentation_intent": intent,
        "evidence_references": (
            [{"evidence_id": "E1", "path": "key_fields.status"}]
            if with_status_reference
            else []
        ),
        "limitation": "NONE",
        "clarification_target": "GENERIC",
    }


def _search_responses() -> list[object]:
    return [
        _understanding(),
        _decision(AgentAction.SEARCH),
        {
            "selected_tool": "work_order_query",
            "arguments": {"work_order_id": "WO20260001"},
            "expected_resolution": "inspect status",
        },
        {
            "evidence_sufficient": True,
            "summary": "reviewed",
            "confirmed_facts": ["status returned"],
            "unresolved_questions": [],
            "recommended_action": "REPLY",
        },
        _decision(AgentAction.REPLY),
        _plan(AgentAction.REPLY, with_status_reference=True),
    ]


def _runtime(
    responses: Iterable[object],
    *,
    registry: ToolRegistry | None = None,
) -> OpsAgentRuntime:
    provider = MockModelProvider(structured_responses=responses, responses=[])
    gateway = ModelGateway(
        routes={
            ModelProfile.CHEAP: ModelRoute(
                profile=ModelProfile.CHEAP,
                provider="mock",
                model="mock-chat",
            )
        },
        providers={"mock": provider},
    )
    return OpsAgentRuntime(gateway, registry)


def _client(
    tmp_path: Path,
    responses: Iterable[object],
    *,
    registry: ToolRegistry | None = None,
    repository: SQLiteRunRepository | None = None,
    raise_server_exceptions: bool = True,
) -> tuple[TestClient, SQLiteRunRepository]:
    store = repository or SQLiteRunRepository(tmp_path / "opsmind.db")
    app = create_app(
        runtime=_runtime(responses, registry=registry),
        run_repository=store,
    )
    return (
        TestClient(app, raise_server_exceptions=raise_server_exceptions),
        store,
    )


def test_chat_success_is_immediately_queryable_as_a_complete_run(
    tmp_path: Path,
) -> None:
    client, _ = _client(tmp_path, _search_responses())
    payload = {
        "message": "WO20260001为什么还在等待？",
        "thread_id": "thread-audit",
        "source_context": {
            "channel": "portal",
            "user_id": "U10023",
            "site_id": "SITE-1",
            "authorization": "must-not-persist",
        },
    }

    chat = client.post("/api/v1/chat", json=payload)
    assert chat.status_code == 200
    chat_body = chat.json()
    detail_response = client.get(f"/api/v1/runs/{chat_body['run_id']}")
    assert detail_response.status_code == 200
    detail = detail_response.json()

    assert detail["run_id"] == chat_body["run_id"]
    assert detail["request_id"] == chat_body["request_id"]
    assert detail["thread_id"] == chat_body["thread_id"] == "thread-audit"
    assert detail["lifecycle_status"] == "SUCCEEDED"
    assert detail["agent_terminal_status"] == chat_body["status"] == "completed"
    assert detail["input_message"] == payload["message"]
    assert detail["source_context"] == {
        "channel": "portal",
        "user_id": "U10023",
        "site_id": "SITE-1",
    }
    assert detail["understanding"] == chat_body["understanding"]
    assert detail["decision"] == chat_body["decision"]
    assert [
        {key: value for key, value in step.items() if key != "sequence"}
        for step in detail["steps"]
    ] == chat_body["trace"]
    assert detail["evidence"] == chat_body["evidence"]
    assert detail["final_reply"] == chat_body["final_reply"]
    assert detail["error_code"] is None
    assert detail["duration_ms"] >= 0
    assert detail["runtime_metadata"]["logical_model_profiles"] == ["CHEAP"]


@pytest.mark.parametrize(
    ("action", "expected_status"),
    [
        (AgentAction.ASK_USER, "waiting_user"),
        (AgentAction.TRANSFER_HUMAN, "transferred"),
    ],
)
def test_business_terminal_is_successful_run_lifecycle(
    tmp_path: Path,
    action: AgentAction,
    expected_status: str,
) -> None:
    client, _ = _client(
        tmp_path,
        [_understanding(), _decision(action), _plan(action)],
    )

    chat = client.post("/api/v1/chat", json={"message": "help"})
    detail = client.get(f"/api/v1/runs/{chat.json()['run_id']}").json()

    assert chat.status_code == 200
    assert chat.json()["status"] == expected_status
    assert detail["lifecycle_status"] == "SUCCEEDED"
    assert detail["agent_terminal_status"] == expected_status


def test_runtime_failure_leaves_safe_normalized_failed_run(tmp_path: Path) -> None:
    secret = "PROVIDER_PAYLOAD_SENTINEL"
    client, repository = _client(
        tmp_path,
        [ModelInvocationError(secret)],
        raise_server_exceptions=False,
    )

    response = client.post("/api/v1/chat", json={"message": "help"})
    body = response.json()
    stored = repository.get(body["error"]["run_id"])

    assert response.status_code == 502
    assert stored is not None
    assert stored.lifecycle_status is RunLifecycleStatus.FAILED
    assert stored.error_code == "MODEL_INVOCATION_FAILED"
    assert stored.agent_terminal_status is None
    assert stored.understanding is None
    assert stored.steps[0].status == "failed"
    assert secret not in stored.model_dump_json()
    assert secret not in response.text


def test_later_structured_failure_preserves_prior_safe_trace_only(
    tmp_path: Path,
) -> None:
    secret = "RAW_MODEL_RESPONSE_SENTINEL"
    client, repository = _client(
        tmp_path,
        [_understanding(), ModelStructuredOutputError(secret)],
        raise_server_exceptions=False,
    )

    response = client.post("/api/v1/chat", json={"message": "help"})
    stored = repository.get(response.json()["error"]["run_id"])

    assert response.status_code == 502
    assert stored is not None
    assert [
        (step.node, step.status, step.summary) for step in stored.steps
    ] == [
        ("understand_request", "completed", "WORKFLOW_ISSUE / DIAGNOSE"),
        (
            "decide_action",
            "failed",
            "MODEL_STRUCTURED_OUTPUT_INVALID",
        ),
    ]
    assert secret not in stored.model_dump_json()


def test_invalid_request_creates_no_run(tmp_path: Path) -> None:
    client, _ = _client(tmp_path, _search_responses())

    response = client.post("/api/v1/chat", json={"message": ""})

    assert response.status_code == 422
    assert "run_id" not in response.json()["error"]
    assert client.get("/api/v1/runs").json() == []


def test_retry_creates_new_request_and_run_for_same_thread(tmp_path: Path) -> None:
    responses = [
        _understanding(),
        _decision(AgentAction.END_CONVERSATION),
        _understanding(),
        _decision(AgentAction.END_CONVERSATION),
    ]
    client, _ = _client(tmp_path, responses)

    first = client.post(
        "/api/v1/chat", json={"message": "done", "thread_id": "same-thread"}
    ).json()
    second = client.post(
        "/api/v1/chat", json={"message": "retry", "thread_id": "same-thread"}
    ).json()

    assert first["thread_id"] == second["thread_id"] == "same-thread"
    assert first["request_id"] != second["request_id"]
    assert first["run_id"] != second["run_id"]
    assert len(client.get("/api/v1/runs").json()) == 2


def test_unknown_run_and_invalid_list_limit_are_typed_safe_errors(
    tmp_path: Path,
) -> None:
    client, _ = _client(tmp_path, _search_responses())

    missing = client.get("/api/v1/runs/not-present")
    invalid_limit = client.get("/api/v1/runs?limit=101")

    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "RUN_NOT_FOUND"
    assert "run_id" not in missing.json()["error"]
    assert invalid_limit.status_code == 422
    assert invalid_limit.json()["error"]["code"] == "REQUEST_VALIDATION_FAILED"


def test_openapi_and_settings_expose_run_contracts(tmp_path: Path) -> None:
    configured = RuntimeSettings.from_env(
        {
            "OPSMIND_MODEL_PROVIDER": "mock",
            "OPSMIND_RUN_STORE_PATH": str(tmp_path / "configured.db"),
            "OPSMIND_BUILD_SHA": "abc123",
        }
    )
    assert configured.run_store_path == tmp_path / "configured.db"
    assert configured.build_sha == "abc123"
    with pytest.raises(ValueError):
        RuntimeSettings.from_env({"OPSMIND_RUN_STORE_PATH": "   "})

    client, _ = _client(tmp_path, _search_responses())
    document = client.get("/openapi.json").json()
    assert set(document["paths"]) >= {
        "/api/v1/chat",
        "/api/v1/runs",
        "/api/v1/runs/{run_id}",
    }
    assert document["paths"]["/api/v1/runs"]["get"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"]["items"] == {
        "$ref": "#/components/schemas/AgentRunSummary"
    }
    assert document["paths"]["/api/v1/runs/{run_id}"]["get"]["responses"][
        "200"
    ]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/AgentRun"
    }


class _FinalizationFailureRepository(SQLiteRunRepository):
    def finalize_succeeded(self, *, run: object) -> None:  # type: ignore[override]
        del run
        raise RunPersistenceError("DATABASE_EXCEPTION_SENTINEL")


class _InitialFailureRepository(SQLiteRunRepository):
    def create_started(self, run: AgentRun) -> None:
        del run
        raise RunPersistenceError("DATABASE_PATH_SECRET_SENTINEL")


def test_initial_persistence_failure_prevents_agent_execution(
    tmp_path: Path,
) -> None:
    provider = MockModelProvider(
        structured_responses=[_understanding()],
        responses=[],
    )
    gateway = ModelGateway(
        routes={
            ModelProfile.CHEAP: ModelRoute(
                profile=ModelProfile.CHEAP,
                provider="mock",
                model="mock-chat",
            )
        },
        providers={"mock": provider},
    )
    app = create_app(
        runtime=OpsAgentRuntime(gateway),
        run_repository=_InitialFailureRepository(tmp_path / "opsmind.db"),
    )

    response = TestClient(app, raise_server_exceptions=False).post(
        "/api/v1/chat", json={"message": "help"}
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "RUN_PERSISTENCE_UNAVAILABLE"
    assert "run_id" not in response.json()["error"]
    assert "DATABASE_PATH_SECRET_SENTINEL" not in response.text
    assert provider.invocation_count == 0


def test_final_persistence_failure_fails_closed_with_started_record(
    tmp_path: Path,
) -> None:
    repository = _FinalizationFailureRepository(tmp_path / "opsmind.db")
    client, _ = _client(
        tmp_path,
        [
            _understanding(),
            _decision(AgentAction.END_CONVERSATION),
            _plan(AgentAction.END_CONVERSATION),
        ],
        repository=repository,
        raise_server_exceptions=False,
    )

    response = client.post("/api/v1/chat", json={"message": "done"})
    body = response.json()
    stored = repository.get(body["error"]["run_id"])

    assert response.status_code == 503
    assert body["error"]["code"] == "RUN_PERSISTENCE_UNAVAILABLE"
    assert "DATABASE_EXCEPTION_SENTINEL" not in response.text
    assert stored is not None
    assert stored.lifecycle_status is RunLifecycleStatus.STARTED


async def _raw_result_tool(
    request: WorkOrderQueryRequest,
) -> WorkOrderQueryResponse:
    return WorkOrderQueryResponse(
        result_status=ToolResultStatus.FOUND,
        work_order_id=request.work_order_id,
        status="APPROVING",
        message="RAW_TOOL_RESULT_SENTINEL",
    )


def _sentinel(value: T) -> StructuredModelResponse[T]:
    return StructuredModelResponse(
        parsed=value,
        response=ModelResponse(
            content="PROMPT_SECRET_SENTINEL PROVIDER_PAYLOAD_SENTINEL",
            provider="mock",
            model="mock-chat",
        ),
    )


def test_internal_provider_and_raw_tool_data_never_reach_sqlite(
    tmp_path: Path,
) -> None:
    registry = ToolRegistry(
        [
            RegisteredTool(
                spec=ToolSpec(
                    name="work_order_query",
                    description="read one work order",
                    mode=ToolMode.READ_ONLY,
                ),
                request_model=WorkOrderQueryRequest,
                response_model=WorkOrderQueryResponse,
                handler=_raw_result_tool,
            )
        ]
    )
    responses = [
        _sentinel(_understanding()),
        _sentinel(_decision(AgentAction.SEARCH)),
        _sentinel(
            ToolSelectionOutput(
                selected_tool="work_order_query",
                arguments={"work_order_id": "WO20260001"},
                expected_resolution="inspect status",
            )
        ),
        _sentinel(
            ToolResultReviewOutput(
                evidence_sufficient=True,
                summary="reviewed",
                confirmed_facts=["status returned"],
                unresolved_questions=[],
                recommended_action=AgentAction.REPLY,
            )
        ),
        _sentinel(_decision(AgentAction.REPLY)),
        _sentinel(
            GroundedResponsePlanOutput.model_validate(
                _plan(AgentAction.REPLY, with_status_reference=True)
            )
        ),
    ]
    client, _ = _client(tmp_path, responses, registry=registry)

    response = client.post(
        "/api/v1/chat",
        json={
            "message": "legitimate user input",
            "source_context": {
                "channel": "portal",
                "private": "TRACEBACK_SECRET_SENTINEL",
            },
        },
    )
    assert response.status_code == 200

    with sqlite3.connect(tmp_path / "opsmind.db") as connection:
        persisted_text = " ".join(
            str(value)
            for table in ("agent_runs", "run_steps", "evidence_records")
            for row in connection.execute(f"SELECT * FROM {table}")
            for value in row
            if value is not None
        )

    for sentinel in (
        "PROMPT_SECRET_SENTINEL",
        "PROVIDER_PAYLOAD_SENTINEL",
        "RAW_TOOL_RESULT_SENTINEL",
        "TRACEBACK_SECRET_SENTINEL",
    ):
        assert sentinel not in persisted_text
    assert "legitimate user input" in persisted_text
    assert "work_order_query: found" in persisted_text
    assert "APPROVING" in persisted_text
