"""Independent second-retest probes for TASK-P1-008 Reviewer findings."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from opsmind.agent.graph import AgentToolCall
from opsmind.agent.schemas import ActionDecisionOutput, RequestUnderstandingOutput
from opsmind.api.app import create_app
from opsmind.api.runtime import AgentRunResult, OpsAgentRuntime
from opsmind.evals import (
    CaseEvaluationContext,
    EvalAssertion,
    EvalAssertionStatus,
    EvalCaseStatus,
    EvalJobLifecycleStatus,
    EvalPersistenceService,
    EvalRunner,
    EvalSuiteLoader,
    EvaluationObservation,
    EvaluationObservationErrorCode,
    EvaluatorRegistry,
    SQLiteEvalRepository,
    ToolCallObservation,
)
from opsmind.execution import AgentExecutionService
from opsmind.models import MockModelProvider, ModelGateway, ModelProfile, ModelRoute
from opsmind.runs import RunLifecycleStatus, RunPersistenceService, SQLiteRunRepository
from opsmind.state import (
    AgentAction,
    DecisionState,
    EvidenceItem,
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


def _successful_result(
    *, argument: str = "LONG_TOOL_ARGUMENT_SENTINEL"
) -> AgentRunResult:
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
                arguments={"work_order_id": argument},
                status="found",
            ),
        ),
    )


class _StaticRuntime:
    def __init__(self, result: AgentRunResult) -> None:
        self.gateway = ModelGateway()
        self.result = result

    async def run_with_trace(self, state: OpsAgentState) -> AgentRunResult:
        del state
        return self.result


@pytest.mark.asyncio
async def test_long_valid_tool_argument_preserves_success_and_bounded_eval_projection(
    tmp_path: Path,
) -> None:
    sentinel = "LONG_TOOL_ARGUMENT_SENTINEL"
    runtime = _StaticRuntime(_successful_result(argument="X" * 600 + sentinel))
    repository = SQLiteRunRepository(tmp_path / "opsmind.db")
    execution = AgentExecutionService(
        cast(OpsAgentRuntime, runtime),
        RunPersistenceService(repository, app_version="second-retest"),
    )

    result = await execution.execute(
        message="check status",
        source_context={},
        request_id="second-retest-request",
        thread_id="second-retest-thread",
    )

    assert result.response.status == "completed"
    observation = result.evaluation_observation
    assert (
        observation.observation_error_code
        is EvaluationObservationErrorCode.TOOL_ARGUMENTS_UNAVAILABLE
    )
    assert observation.tool_calls[0].arguments == {}
    assert sentinel not in observation.model_dump_json()
    assert len(observation.model_dump_json().encode("utf-8")) <= 128 * 1_024

    stored = repository.get(result.run_id)
    assert stored is not None
    assert stored.lifecycle_status is RunLifecycleStatus.SUCCEEDED
    assert stored.error_code is None


def test_chat_endpoint_keeps_long_valid_tool_argument_run_successful(
    tmp_path: Path,
) -> None:
    sentinel = "CHAT_LONG_TOOL_ARGUMENT_SENTINEL"
    runtime = _StaticRuntime(_successful_result(argument="Y" * 600 + sentinel))
    repository = SQLiteRunRepository(tmp_path / "opsmind.db")
    app = create_app(
        runtime=cast(OpsAgentRuntime, runtime),
        run_repository=repository,
    )

    response = TestClient(app).post(
        "/api/v1/chat",
        json={"message": "check status", "thread_id": "second-retest-chat"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["final_reply"] == "completed"
    stored = repository.get(body["run_id"])
    assert stored is not None
    assert stored.lifecycle_status is RunLifecycleStatus.SUCCEEDED
    assert stored.error_code is None


@pytest.mark.parametrize(
    "source_code",
    [
        "from opsmind.execution import AgentExecutionService; "
        "assert AgentExecutionService.__name__ == 'AgentExecutionService'",
        "import opsmind.evals; "
        "from opsmind.execution import AgentExecutionService; "
        "assert AgentExecutionService.__name__ == 'AgentExecutionService'",
        "from opsmind.evals import EvalRunner; "
        "from opsmind.execution import AgentExecutionService; "
        "assert EvalRunner and AgentExecutionService",
    ],
)
def test_execution_direct_import_is_order_independent_in_fresh_processes(
    source_code: str,
) -> None:
    source_root = Path(__file__).resolve().parents[1] / "src"
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(source_root)

    probe = subprocess.run(
        [sys.executable, "-c", source_code],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert probe.returncode == 0, probe.stderr


def _understanding() -> RequestUnderstandingOutput:
    return RequestUnderstandingOutput(
        primary_intent=PrimaryIntent.WORKFLOW_ISSUE,
        request_type=RequestType.DIAGNOSE,
        symptom="second retest",
        entities={},
        risk_signal=RiskSignal.NONE,
        uncertainty=None,
    )


def _queued_runtime(
    responses: list[object],
) -> OpsAgentRuntime:
    provider = MockModelProvider(structured_responses=responses, responses=[])
    gateway = ModelGateway(
        routes={
            ModelProfile.CHEAP: ModelRoute(
                profile=ModelProfile.CHEAP,
                provider="mock",
                model="second-retest-mock",
            )
        },
        providers={"mock": provider},
    )
    return OpsAgentRuntime(gateway)


def _write_suite(path: Path, assertions: list[dict[str, object]]) -> EvalSuiteLoader:
    payload = {
        "schema_version": 1,
        "suite_id": "invalid-result-suite",
        "suite_version": "1.0",
        "description": "second retest",
        "cases": [
            {
                "case_id": "C1",
                "title": "one",
                "turns": [{"message": "done"}],
                "source_context": {},
                "assertions": assertions,
            }
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return EvalSuiteLoader(path)


@pytest.mark.asyncio
async def test_invalid_evaluator_return_is_case_error_but_job_completes(
    tmp_path: Path,
) -> None:
    def invalid_evaluator(
        assertion: EvalAssertion,
        context: CaseEvaluationContext,
    ) -> Any:
        del assertion, context
        return {"invalid": "SECOND_RETEST_PRIVATE_SENTINEL"}

    registry = EvaluatorRegistry({"invalid": invalid_evaluator})
    suite_path = tmp_path / "invalid-result.json"
    loader = _write_suite(
        suite_path,
        [
            {
                "assertion_id": "invalid-result",
                "type": "invalid",
                "expected": True,
            }
        ],
    )
    # The loader must use the same custom registry that the runner dispatches.
    loader = EvalSuiteLoader(suite_path, evaluator_registry=registry)
    database_path = tmp_path / "opsmind.db"
    run_repository = SQLiteRunRepository(database_path)
    execution = AgentExecutionService(
        _queued_runtime(
            [
                _understanding(),
                ActionDecisionOutput(
                    action=AgentAction.END_CONVERSATION,
                    goal="close",
                    rationale="done",
                ),
            ]
        ),
        RunPersistenceService(run_repository, app_version="second-retest"),
    )
    eval_repository = SQLiteEvalRepository(database_path)
    persistence = EvalPersistenceService(
        eval_repository,
        app_version="second-retest",
        run_repository=run_repository,
    )
    runner = EvalRunner(
        loader=loader,
        execution_service=execution,
        persistence=persistence,
        evaluators=registry,
    )

    job = await runner.run_suite("invalid-result-suite")

    assert job.lifecycle_status is EvalJobLifecycleStatus.COMPLETED
    assert job.case_results[0].status is EvalCaseStatus.ERROR
    assert job.error_count == 1
    assert job.case_results[0].assertions[0].status is EvalAssertionStatus.ERROR
    assert "SECOND_RETEST_PRIVATE_SENTINEL" not in job.model_dump_json()
    stored = eval_repository.get(job.eval_job_id)
    assert stored is not None
    assert stored.lifecycle_status is EvalJobLifecycleStatus.COMPLETED


def _observation(
    *,
    request_type: RequestType = RequestType.DIAGNOSE,
    action: AgentAction = AgentAction.SEARCH,
    thread_id: str = "thread-1",
    run_id: str = "run-1",
    request_id: str = "request-1",
    observation_error_code: EvaluationObservationErrorCode | None = None,
    current_handler: str = "U10108",
    waiting_hours: float = 4.0,
) -> EvaluationObservation:
    return EvaluationObservation(
        run_id=run_id,
        request_id=request_id,
        thread_id=thread_id,
        lifecycle_status="SUCCEEDED",
        understanding=UnderstandingState(
            primary_intent=PrimaryIntent.WORKFLOW_ISSUE,
            request_type=request_type,
            risk_signal=RiskSignal.NONE,
            entities={"work_order_id": "WO20260001"},
        ),
        final_decision=DecisionState(
            action=action,
            goal="inspect",
            rationale="second retest observation",
        ),
        action_sequence=[action],
        tool_calls=[
            ToolCallObservation(
                tool_name="work_order_query",
                arguments={"work_order_id": "WO20260001"},
                status="found",
            )
        ],
        loop=LoopState(round_count=1, tool_call_count=1),
        evidence=[
            EvidenceItem(
                evidence_id="E1",
                source="work_order_query",
                summary="second retest result",
                key_fields={
                    "status": "APPROVING",
                    "current_handler": current_handler,
                    "waiting_hours": waiting_hours,
                    "abnormal": False,
                    "missing_permissions": ["EQUIPMENT_LEDGER_VIEW"],
                },
                metadata={},
                timestamp=datetime.now(UTC),
            )
        ],
        handoff=HandoffState(required=action is AgentAction.TRANSFER_HUMAN),
        observation_error_code=observation_error_code,
        terminal_status=TaskStatus.RESOLVED,
        reply_nonempty=True,
        loop_converged=True,
    )


_EVALUATOR_MATRIX: tuple[tuple[str, object, object, bool], ...] = (
    ("run_lifecycle_succeeded", True, False, False),
    ("intent_in", ["WORKFLOW_ISSUE"], ["ACCESS_ISSUE"], False),
    ("request_type_in", ["DIAGNOSE"], ["HOW_TO"], False),
    ("risk_signal_in", ["NONE"], ["BROAD_OUTAGE"], False),
    ("final_action_in", ["SEARCH"], ["REPLY"], False),
    ("terminal_status_in", ["RESOLVED"], ["WAITING_USER"], False),
    ("required_tool_used", ["work_order_query"], ["permission_query"], False),
    ("forbidden_tool_not_used", ["permission_mutation"], ["work_order_query"], False),
    (
        "tool_argument_equals",
        {"tool": "work_order_query", "field": "work_order_id", "value": "WO20260001"},
        {"tool": "work_order_query", "field": "work_order_id", "value": "WO99999999"},
        False,
    ),
    ("tool_call_count_lte", 1, 0, False),
    ("evidence_count_gte", 1, 2, False),
    ("evidence_source_present", ["work_order_query"], ["permission_query"], False),
    (
        "evidence_field_equals",
        {"source": "work_order_query", "field": "status", "value": "APPROVING"},
        {"source": "work_order_query", "field": "status", "value": "FAILED"},
        False,
    ),
    (
        "evidence_field_contains",
        {
            "source": "work_order_query",
            "field": "missing_permissions",
            "value": "EQUIPMENT_LEDGER_VIEW",
        },
        {
            "source": "work_order_query",
            "field": "missing_permissions",
            "value": "MISSING_PERMISSION",
        },
        False,
    ),
    ("reply_nonempty", True, False, False),
    ("handoff_required", False, True, False),
    ("same_thread_across_turns", True, False, True),
    ("loop_converged", True, False, False),
)


def _matrix_context(
    *,
    multi_turn: bool,
    observation_error_code: EvaluationObservationErrorCode | None = None,
) -> CaseEvaluationContext:
    count = 2 if multi_turn else 1
    return CaseEvaluationContext(
        tuple(
            _observation(
                run_id=f"run-{index}",
                request_id=f"request-{index}",
                observation_error_code=observation_error_code,
            )
            for index in range(count)
        )
    )


def test_complete_18_evaluator_matrix_has_pass_fail_and_invalid_paths() -> None:
    registry = EvaluatorRegistry()
    assert {row[0] for row in _EVALUATOR_MATRIX} == set(registry.types)

    for (
        evaluator_type,
        passing_expected,
        failing_expected,
        multi_turn,
    ) in _EVALUATOR_MATRIX:
        passing = registry.evaluate(
            EvalAssertion(
                assertion_id=f"{evaluator_type}-pass",
                type=evaluator_type,
                expected=passing_expected,
            ),
            _matrix_context(multi_turn=multi_turn),
        )
        failing = registry.evaluate(
            EvalAssertion(
                assertion_id=f"{evaluator_type}-fail",
                type=evaluator_type,
                expected=failing_expected,
            ),
            _matrix_context(multi_turn=multi_turn),
        )
        invalid = registry.evaluate(
            EvalAssertion(
                assertion_id=f"{evaluator_type}-invalid",
                type=evaluator_type,
                expected=passing_expected,
            ),
            _matrix_context(
                multi_turn=multi_turn,
                observation_error_code=(
                    EvaluationObservationErrorCode.TOOL_ARGUMENTS_UNAVAILABLE
                ),
            ),
        )
        assert passing.status is EvalAssertionStatus.PASS, evaluator_type
        assert failing.status is EvalAssertionStatus.FAIL, evaluator_type
        assert invalid.status is EvalAssertionStatus.ERROR, evaluator_type


def test_golden_c05_c06_truths_are_blocking_and_wrong_values_fail() -> None:
    suite = EvalSuiteLoader().load()
    cases = {case.case_id: case for case in suite.cases}
    c05 = {assertion.assertion_id: assertion for assertion in cases["C05"].assertions}
    c06 = {assertion.assertion_id: assertion for assertion in cases["C06"].assertions}

    assert c05["handler"].blocking is True
    assert c05["waiting"].blocking is True
    assert c06["request"].blocking is True
    assert c06["request"].expected == ["DIAGNOSE"]

    registry = EvaluatorRegistry()
    correct = CaseEvaluationContext((_observation(),))
    wrong_handler = CaseEvaluationContext(
        (_observation(current_handler="U99999"),)
    )
    wrong_waiting = CaseEvaluationContext(
        (_observation(waiting_hours=5),)
    )
    wrong_request = CaseEvaluationContext(
        (_observation(request_type=RequestType.HOW_TO),)
    )

    for assertion_id, context in (
        ("handler", wrong_handler),
        ("waiting", wrong_waiting),
    ):
        assertion = c05[assertion_id]
        assert (
            registry.evaluate(assertion, correct).status is EvalAssertionStatus.PASS
        )
        assert (
            registry.evaluate(assertion, context).status is EvalAssertionStatus.FAIL
        )

    assert (
        registry.evaluate(c06["request"], correct).status is EvalAssertionStatus.PASS
    )
    assert (
        registry.evaluate(c06["request"], wrong_request).status
        is EvalAssertionStatus.FAIL
    )
