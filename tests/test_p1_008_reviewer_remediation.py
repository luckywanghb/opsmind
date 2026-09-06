from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import cast

import pytest
from fastapi.testclient import TestClient

from opsmind.agent.graph import AgentToolCall
from opsmind.api.app import create_app
from opsmind.api.runtime import AgentRunResult, OpsAgentRuntime
from opsmind.evals import EvaluationObservationErrorCode
from opsmind.execution import AgentExecutionService
from opsmind.models import ModelGateway
from opsmind.runs import (
    RunLifecycleStatus,
    RunPersistenceService,
    SQLiteRunRepository,
)
from opsmind.state import (
    AgentAction,
    DecisionState,
    HandoffState,
    LoopState,
    OpsAgentState,
    PrimaryIntent,
    RequestType,
    ResponseState,
    RiskSignal,
    TaskState,
    TaskStatus,
    UnderstandingState,
)


def _successful_result() -> AgentRunResult:
    return AgentRunResult(
        state=OpsAgentState(
            understanding=UnderstandingState(
                primary_intent=PrimaryIntent.WORKFLOW_ISSUE,
                request_type=RequestType.DIAGNOSE,
                symptom="completed read-only lookup",
                entities={},
                risk_signal=RiskSignal.NONE,
            ),
            task=TaskState(objective="reply", status=TaskStatus.RESOLVED),
            loop=LoopState(round_count=1, tool_call_count=1),
            decision=DecisionState(
                action=AgentAction.REPLY,
                goal="reply",
                rationale="lookup completed",
            ),
            response=ResponseState(message="completed", is_final=True),
            handoff=HandoffState(),
        ),
        invocations=(),
        tool_calls=(
            AgentToolCall(
                tool_name="work_order_query",
                arguments={"work_order_id": "W" * 600},
                status="found",
            ),
        ),
    )


class _LongArgumentRuntime:
    def __init__(self) -> None:
        self.gateway = ModelGateway()
        self.result = _successful_result()

    async def run_with_trace(self, state: OpsAgentState) -> AgentRunResult:
        del state
        return self.result


@pytest.mark.asyncio
async def test_long_valid_tool_argument_keeps_chat_run_successful_and_bounded_for_eval(
    tmp_path: Path,
) -> None:
    runtime = _LongArgumentRuntime()
    repository = SQLiteRunRepository(tmp_path / "opsmind.db")
    execution = AgentExecutionService(
        cast(OpsAgentRuntime, runtime),
        RunPersistenceService(repository, app_version="test"),
    )

    result = await execution.execute(
        message="check status",
        source_context={},
        request_id="request-long-argument",
        thread_id="thread-long-argument",
    )

    assert result.response.status == "completed"
    assert (
        result.evaluation_observation.observation_error_code
        is EvaluationObservationErrorCode.TOOL_ARGUMENTS_UNAVAILABLE
    )
    assert result.evaluation_observation.tool_calls[0].arguments == {}
    assert (
        result.evaluation_observation.tool_calls[0].error_code
        == EvaluationObservationErrorCode.TOOL_ARGUMENTS_UNAVAILABLE.value
    )
    stored = repository.get(result.run_id)
    assert stored is not None
    assert stored.lifecycle_status is RunLifecycleStatus.SUCCEEDED


def test_chat_endpoint_keeps_successful_run_for_long_valid_tool_argument(
    tmp_path: Path,
) -> None:
    runtime = _LongArgumentRuntime()
    repository = SQLiteRunRepository(tmp_path / "opsmind.db")
    app = create_app(
        runtime=cast(OpsAgentRuntime, runtime),
        run_repository=repository,
    )

    response = TestClient(app).post(
        "/api/v1/chat",
        json={"message": "check status", "thread_id": "thread-chat"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["final_reply"] == "completed"
    stored = repository.get(body["run_id"])
    assert stored is not None
    assert stored.lifecycle_status is RunLifecycleStatus.SUCCEEDED


def test_execution_direct_import_is_order_independent_in_a_fresh_process() -> None:
    source_root = Path(__file__).resolve().parents[1] / "src"
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(source_root)

    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            "from opsmind.execution import AgentExecutionService; "
            "assert AgentExecutionService.__name__ == 'AgentExecutionService'",
        ],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert probe.returncode == 0, probe.stderr
