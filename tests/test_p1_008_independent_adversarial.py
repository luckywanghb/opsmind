"""Independent adversarial probes for TASK-P1-008.

These tests are intentionally separate from the Developer-authored eval
tests.  They exercise integrity, isolation, type-strictness, persistence
failure, and safe-boundary behavior.  This file must remain test-only; it does
not replace or monkeypatch product implementation in normal paths.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from opsmind.agent.schemas import ActionDecisionOutput, RequestUnderstandingOutput
from opsmind.api.app import create_app
from opsmind.api.runtime import OpsAgentRuntime
from opsmind.evals import (
    CaseEvaluationContext,
    EvalAssertion,
    EvalAssertionResult,
    EvalAssertionStatus,
    EvalCaseResult,
    EvalCaseStatus,
    EvalDataIntegrityError,
    EvalJobLifecycleStatus,
    EvalPersistenceError,
    EvalPersistenceService,
    EvalRunner,
    EvalSuiteLoader,
    EvalSuiteLoadError,
    EvaluationObservation,
    EvaluatorRegistry,
    SQLiteEvalRepository,
    ToolCallObservation,
)
from opsmind.execution import AgentExecutionService
from opsmind.models import (
    MockModelProvider,
    ModelGateway,
    ModelProfile,
    ModelRoute,
    ModelStructuredOutputError,
)
from opsmind.runs import RunPersistenceService, SQLiteRunRepository
from opsmind.state import (
    AgentAction,
    DecisionState,
    EvidenceItem,
    HandoffState,
    LoopState,
    PrimaryIntent,
    RequestType,
    RiskSignal,
    UnderstandingState,
)
from opsmind.tools import (
    RegisteredTool,
    ToolMode,
    ToolRegistry,
    ToolSpec,
    WorkOrderQueryRequest,
    WorkOrderQueryResponse,
)


def _suite_payload(
    *,
    suite_id: str = "independent-suite",
    case_id: str = "C1",
    message: str = "done",
    assertions: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "suite_id": suite_id,
        "suite_version": "1.0",
        "description": "independent adversarial suite",
        "cases": [
            {
                "case_id": case_id,
                "title": "independent case",
                "turns": [{"message": message}],
                "source_context": {"channel": "tester"},
                "assertions": assertions
                or [
                    {
                        "assertion_id": "action",
                        "type": "final_action_in",
                        "expected": ["END_CONVERSATION"],
                    }
                ],
            }
        ],
    }


def _write_suite(path: Path, payload: dict[str, object]) -> EvalSuiteLoader:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return EvalSuiteLoader(path)


def _understanding() -> RequestUnderstandingOutput:
    return RequestUnderstandingOutput(
        primary_intent=PrimaryIntent.WORKFLOW_ISSUE,
        request_type=RequestType.DIAGNOSE,
        symptom="independent test",
        entities={},
        risk_signal=RiskSignal.NONE,
        uncertainty=None,
    )


def _queued_runtime(
    responses: list[object],
) -> tuple[OpsAgentRuntime, MockModelProvider]:
    provider = MockModelProvider(structured_responses=responses, responses=[])
    gateway = ModelGateway(
        routes={
            ModelProfile.CHEAP: ModelRoute(
                profile=ModelProfile.CHEAP,
                provider="mock",
                model="independent-mock",
            )
        },
        providers={"mock": provider},
    )
    return OpsAgentRuntime(gateway), provider


def _case_result(job_id: str, *, run_id: str = "run-1") -> EvalCaseResult:
    started = datetime.now(UTC)
    return EvalCaseResult(
        eval_job_id=job_id,
        case_id="C1",
        title="independent case",
        status=EvalCaseStatus.PASS,
        run_ids=[run_id],
        assertions=[
            EvalAssertionResult(
                assertion_id="lifecycle",
                type="run_lifecycle_succeeded",
                blocking=True,
                status=EvalAssertionStatus.PASS,
                expected_safe=True,
                actual_safe=True,
                message="run lifecycle checked",
            )
        ],
        started_at=started,
        completed_at=datetime.now(UTC),
        duration_ms=1.0,
    )


def _observation(
    *,
    run_id: str = "run-1",
    request_id: str = "request-1",
    thread_id: str = "thread-1",
    lifecycle_status: str = "SUCCEEDED",
    terminal_status: str = "RESOLVED",
) -> EvaluationObservation:
    return EvaluationObservation(
        run_id=run_id,
        request_id=request_id,
        thread_id=thread_id,
        lifecycle_status=lifecycle_status,
        understanding=UnderstandingState(
            primary_intent=PrimaryIntent.WORKFLOW_ISSUE,
            request_type=RequestType.DIAGNOSE,
            risk_signal=RiskSignal.NONE,
            entities={"work_order_id": "WO20260001"},
        ),
        final_decision=DecisionState(
            action=AgentAction.SEARCH,
            goal="inspect",
            rationale="typed observation",
        ),
        action_sequence=[AgentAction.SEARCH],
        tool_calls=[
            ToolCallObservation(
                tool_name="work_order_query",
                arguments={
                    "work_order_id": "WO20260001",
                    "bool_flag": False,
                },
                status="found",
            )
        ],
        loop=LoopState(round_count=1, tool_call_count=1),
        evidence=[
            EvidenceItem(
                evidence_id="E1",
                source="work_order_query",
                summary="typed result",
                key_fields={
                    "status": "APPROVING",
                    "abnormal": False,
                    "bool_flag": False,
                },
                metadata={},
                timestamp=datetime.now(UTC),
            )
        ],
        handoff=HandoffState(required=False),
        terminal_status=terminal_status,
        reply_nonempty=True,
        loop_converged=True,
    )


def test_evidence_and_tool_argument_equality_is_json_type_strict() -> None:
    """False must not satisfy an evaluator expectation of numeric zero."""

    context = CaseEvaluationContext((_observation(),))
    registry = EvaluatorRegistry()
    evidence = registry.evaluate(
        EvalAssertion(
            assertion_id="evidence-type",
            type="evidence_field_equals",
            expected={"source": "work_order_query", "field": "bool_flag", "value": 0},
        ),
        context,
    )
    argument = registry.evaluate(
        EvalAssertion(
            assertion_id="argument-type",
            type="tool_argument_equals",
            expected={"tool": "work_order_query", "field": "bool_flag", "value": 0},
        ),
        context,
    )

    assert evidence.status is EvalAssertionStatus.FAIL
    assert argument.status is EvalAssertionStatus.FAIL

    wrong_value = registry.evaluate(
        EvalAssertion(
            assertion_id="argument-value",
            type="tool_argument_equals",
            expected={
                "tool": "work_order_query",
                "field": "work_order_id",
                "value": "WO99999999",
            },
        ),
        context,
    )
    missing_tool = registry.evaluate(
        EvalAssertion(
            assertion_id="missing-tool",
            type="required_tool_used",
            expected=["permission_query"],
        ),
        context,
    )
    assert wrong_value.status is EvalAssertionStatus.FAIL
    assert missing_tool.status is EvalAssertionStatus.FAIL


def test_invalid_terminal_status_observation_is_an_evaluator_error() -> None:
    """A non-contract terminal status must not be accepted as a match."""

    observation = _observation(terminal_status="NOT_A_TASK_STATUS")
    result = EvaluatorRegistry().evaluate(
        EvalAssertion(
            assertion_id="terminal",
            type="terminal_status_in",
            expected=["NOT_A_TASK_STATUS"],
        ),
        CaseEvaluationContext((observation,)),
    )

    assert result.status is EvalAssertionStatus.ERROR


@pytest.mark.asyncio
async def test_known_gap_does_not_convert_a_blocking_failure_to_pass(
    tmp_path: Path,
) -> None:
    """Known-gap metadata must remain explanatory rather than a waiver."""

    payload = _suite_payload(
        assertions=[
            {
                "assertion_id": "wrong-action",
                "type": "final_action_in",
                "expected": ["REPLY"],
            }
        ]
    )
    cases = payload["cases"]
    assert isinstance(cases, list)
    assert isinstance(cases[0], dict)
    cases[0]["known_gap"] = "INTENTIONALLY_UNIMPLEMENTED"
    loader = _write_suite(tmp_path / "known-gap.json", payload)
    runtime, _ = _queued_runtime(
        [
            _understanding(),
            ActionDecisionOutput(
                action=AgentAction.END_CONVERSATION,
                goal="close",
                rationale="done",
            ),
        ]
    )
    database_path = tmp_path / "opsmind.db"
    run_repository = SQLiteRunRepository(database_path)
    execution_service = AgentExecutionService(
        runtime,
        RunPersistenceService(run_repository, app_version="tester"),
    )
    eval_repository = SQLiteEvalRepository(database_path)
    persistence = EvalPersistenceService(
        eval_repository,
        app_version="tester",
        run_repository=run_repository,
    )
    runner = EvalRunner(
        loader=loader,
        execution_service=execution_service,
        persistence=persistence,
    )

    job = await runner.run_suite("independent-suite")

    assert job.lifecycle_status is EvalJobLifecycleStatus.COMPLETED
    assert job.case_results[0].status is EvalCaseStatus.FAIL
    assert job.case_results[0].known_gap == "INTENTIONALLY_UNIMPLEMENTED"
    assert (job.passed_count, job.failed_count, job.error_count) == (0, 1, 0)


def test_deeply_nested_suite_is_rejected_as_a_typed_suite_error() -> None:
    """Syntactically valid JSON must not escape loader error normalization."""

    depth = 1_200
    nested = "{\"x\":" * depth + "null" + "}" * depth
    payload = _suite_payload()
    # Keep the deeply nested object as JSON text.  Parsing it here would move
    # the failure out of the loader boundary that this test is exercising.
    content = json.dumps(payload).replace('{"channel": "tester"}', nested, 1)

    with pytest.raises(EvalSuiteLoadError):
        EvalSuiteLoader().loads(content)


def test_api_normalizes_deeply_nested_suite_to_eval_suite_error(
    tmp_path: Path,
) -> None:
    """Malformed suite depth must not escape as a generic HTTP 500."""

    depth = 1_200
    nested = "{\"x\":" * depth + "null" + "}" * depth
    content = json.dumps(_suite_payload()).replace('{"channel": "tester"}', nested, 1)
    suite_path = tmp_path / "deep-suite.json"
    suite_path.write_text(content, encoding="utf-8")
    database_path = tmp_path / "opsmind.db"
    client = TestClient(
        create_app(
            run_repository=SQLiteRunRepository(database_path),
            eval_suite_loader=EvalSuiteLoader(suite_path),
        ),
        raise_server_exceptions=False,
    )

    response = client.post(
        "/api/v1/evals/run",
        json={"suite_id": "independent-suite"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "EVAL_SUITE_INVALID"


@pytest.mark.parametrize(
    "invalid_assertion",
    [
        {
            "assertion_id": "bad-expectation",
            "type": "tool_argument_equals",
            "expected": {"tool": "work_order_query"},
        },
        {
            "assertion_id": "bad-expectation",
            "type": "intent_in",
            "expected": {"intent": "WORKFLOW_ISSUE"},
        },
        {
            "assertion_id": "bad-turn",
            "type": "reply_nonempty",
            "expected": True,
            "turn_index": 1,
        },
    ],
)
def test_suite_rejects_evaluator_invalid_expectations(
    invalid_assertion: dict[str, object],
) -> None:
    """Malformed evaluator parameters must fail load, before a job starts."""

    payload = _suite_payload(assertions=[invalid_assertion])

    with pytest.raises(EvalSuiteLoadError):
        EvalSuiteLoader().loads(json.dumps(payload))


def test_eval_persistence_service_cannot_commit_a_fabricated_run_link(
    tmp_path: Path,
) -> None:
    """The canonical eval persistence service must enforce run referential integrity."""

    path = tmp_path / "opsmind.db"
    repository = SQLiteEvalRepository(path)
    # Omitting the run repository is an exposed constructor path.  It must not
    # silently turn an eval relation into an unverifiable foreign key.
    persistence = EvalPersistenceService(repository, app_version="tester")
    active = persistence.start(
        suite_id="independent-suite",
        suite_version="1.0",
        case_count=1,
        runtime_identity="mock",
    )

    with pytest.raises(EvalPersistenceError, match="Agent run reference"):
        persistence.complete(active, case_results=[_case_result(active.eval_job_id)])

    stored = repository.get(active.eval_job_id)
    assert stored is not None
    assert stored.lifecycle_status is EvalJobLifecycleStatus.STARTED


class _FinalizeFailureRepository:
    """Repository double that fails only the completed-job commit."""

    def __init__(self, inner: SQLiteEvalRepository) -> None:
        self.inner = inner
        self.started: Any = None

    def create_started(self, job: Any) -> None:
        self.started = job
        self.inner.create_started(job)

    def finalize_completed(self, *, job: Any) -> None:
        del job
        raise EvalPersistenceError("injected eval finalization outage")

    def finalize_failed(self, *, job: Any) -> None:
        self.inner.finalize_failed(job=job)

    def get(self, eval_job_id: str) -> Any:
        return self.inner.get(eval_job_id)

    def list(self, *, limit: int) -> list[Any]:
        return self.inner.list(limit=limit)


@pytest.mark.asyncio
async def test_runner_marks_job_failed_when_terminal_persistence_fails(
    tmp_path: Path,
) -> None:
    """A fatal finalization error must not leave a durable STARTED job."""

    loader = _write_suite(tmp_path / "suite.json", _suite_payload())
    runtime, _ = _queued_runtime(
        [
            _understanding(),
            ActionDecisionOutput(
                action=AgentAction.END_CONVERSATION,
                goal="close",
                rationale="done",
            ),
        ]
    )
    run_repository = SQLiteRunRepository(tmp_path / "opsmind.db")
    execution_service = AgentExecutionService(
        runtime,
        RunPersistenceService(run_repository, app_version="tester"),
    )
    eval_repository = SQLiteEvalRepository(tmp_path / "opsmind.db")
    failing_repository = _FinalizeFailureRepository(eval_repository)
    persistence = EvalPersistenceService(
        failing_repository,
        app_version="tester",
        run_repository=run_repository,
    )
    runner = EvalRunner(
        loader=loader,
        execution_service=execution_service,
        persistence=persistence,
    )

    with pytest.raises(EvalPersistenceError):
        await runner.run_suite("independent-suite")

    assert failing_repository.started is not None
    stored = eval_repository.get(failing_repository.started.eval_job_id)
    assert stored is not None
    assert stored.lifecycle_status is EvalJobLifecycleStatus.FAILED


def _build_concurrent_runner(
    *,
    suite_path: Path,
    suite_id: str,
    message: str,
    database_path: Path,
    eval_repository: SQLiteEvalRepository,
) -> EvalRunner:
    loader = _write_suite(
        suite_path,
        _suite_payload(suite_id=suite_id, message=message),
    )
    runtime, _ = _queued_runtime(
        [
            _understanding(),
            ActionDecisionOutput(
                action=AgentAction.END_CONVERSATION,
                goal="close",
                rationale=message,
            ),
        ]
    )
    run_repository = SQLiteRunRepository(database_path)
    execution_service = AgentExecutionService(
        runtime,
        RunPersistenceService(run_repository, app_version="tester"),
    )
    persistence = EvalPersistenceService(
        eval_repository,
        app_version="tester",
        run_repository=run_repository,
    )
    return EvalRunner(
        loader=loader,
        execution_service=execution_service,
        persistence=persistence,
    )


def test_concurrent_eval_jobs_are_isolated_in_one_store(tmp_path: Path) -> None:
    """Concurrent jobs must retain only their own case and run relations."""

    database_path = tmp_path / "opsmind.db"
    eval_repository = SQLiteEvalRepository(database_path)
    runner_a = _build_concurrent_runner(
        suite_path=tmp_path / "suite-a.json",
        suite_id="suite-a",
        message="case-a",
        database_path=database_path,
        eval_repository=eval_repository,
    )
    runner_b = _build_concurrent_runner(
        suite_path=tmp_path / "suite-b.json",
        suite_id="suite-b",
        message="case-b",
        database_path=database_path,
        eval_repository=eval_repository,
    )

    def run(runner: EvalRunner, suite_id: str) -> Any:
        return asyncio.run(runner.run_suite(suite_id))

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(run, runner_a, "suite-a"),
            executor.submit(run, runner_b, "suite-b"),
        ]
        jobs = [future.result(timeout=15) for future in futures]

    assert {job.suite_id for job in jobs} == {"suite-a", "suite-b"}
    assert all(
        job.lifecycle_status is EvalJobLifecycleStatus.COMPLETED for job in jobs
    )
    assert len({job.eval_job_id for job in jobs}) == 2
    assert all(len(job.case_results) == 1 for job in jobs)
    assert all(len(job.case_runs) == 1 for job in jobs)
    assert len({job.case_runs[0].run_id for job in jobs}) == 2
    run_repository = SQLiteRunRepository(database_path)
    runs = [
        run_repository.get(job.case_runs[0].run_id)
        for job in jobs
    ]
    assert all(run is not None for run in runs)
    assert len({run.thread_id for run in runs if run is not None}) == 2
    assert {run.input_message for run in runs if run is not None} == {
        "case-a",
        "case-b",
    }
    for job in jobs:
        stored = eval_repository.get(job.eval_job_id)
        assert stored is not None
        assert stored.suite_id == job.suite_id
        assert {item.eval_job_id for item in stored.case_results} == {job.eval_job_id}
        assert {item.eval_job_id for item in stored.case_runs} == {job.eval_job_id}


@pytest.mark.asyncio
async def test_multiturn_links_keep_thread_but_rotate_request_and_run_ids(
    tmp_path: Path,
) -> None:
    """C12-style execution must not reuse a request or run identity."""

    payload = _suite_payload(
        suite_id="multi-suite",
        message="first",
        assertions=[
            {
                "assertion_id": "identity",
                "type": "same_thread_across_turns",
                "expected": True,
            }
        ],
    )
    payload["cases"][0]["turns"] = [  # type: ignore[index]
        {"message": "first"},
        {"message": "second"},
    ]
    loader = _write_suite(tmp_path / "multi.json", payload)
    runtime, provider = _queued_runtime(
        [
            _understanding(),
            ActionDecisionOutput(
                action=AgentAction.END_CONVERSATION,
                goal="close",
                rationale="first",
            ),
            _understanding(),
            ActionDecisionOutput(
                action=AgentAction.END_CONVERSATION,
                goal="close",
                rationale="second",
            ),
        ]
    )
    database_path = tmp_path / "opsmind.db"
    run_repository = SQLiteRunRepository(database_path)
    execution_service = AgentExecutionService(
        runtime,
        RunPersistenceService(run_repository, app_version="tester"),
    )
    eval_repository = SQLiteEvalRepository(database_path)
    persistence = EvalPersistenceService(
        eval_repository,
        app_version="tester",
        run_repository=run_repository,
    )
    runner = EvalRunner(
        loader=loader,
        execution_service=execution_service,
        persistence=persistence,
    )

    job = await runner.run_suite("multi-suite")
    assert job.case_results[0].status is EvalCaseStatus.PASS
    runs = [run_repository.get(run_id) for run_id in job.case_results[0].run_ids]
    assert all(run is not None for run in runs)
    assert len({run.thread_id for run in runs if run is not None}) == 1
    assert len({run.request_id for run in runs if run is not None}) == 2
    assert len({run.run_id for run in runs if run is not None}) == 2
    assert [run.input_message for run in runs if run is not None] == [
        "first",
        "second",
    ]
    second_messages = provider.history[2].messages
    second_prompt = "\n".join(message.content for message in second_messages)
    assert "second" in second_prompt
    assert "first" not in second_prompt


@pytest.mark.asyncio
async def test_eval_error_persists_only_safe_codes_and_no_provider_sentinel(
    tmp_path: Path,
) -> None:
    """Provider exception text must not cross the run/eval persistence boundary."""

    loader = _write_suite(
        tmp_path / "suite.json",
        _suite_payload(
            assertions=[
                {
                    "assertion_id": "lifecycle",
                    "type": "run_lifecycle_succeeded",
                    "expected": True,
                }
            ]
        ),
    )
    runtime, _ = _queued_runtime(
        [ModelStructuredOutputError("RAW_PROVIDER_SENTINEL TRACEBACK_SENTINEL")]
    )
    database_path = tmp_path / "opsmind.db"
    run_repository = SQLiteRunRepository(database_path)
    from opsmind.execution import AgentExecutionService

    execution_service = AgentExecutionService(
        runtime,
        RunPersistenceService(run_repository, app_version="tester"),
    )
    eval_repository = SQLiteEvalRepository(database_path)
    persistence = EvalPersistenceService(
        eval_repository,
        app_version="tester",
        run_repository=run_repository,
    )
    runner = EvalRunner(
        loader=loader,
        execution_service=execution_service,
        persistence=persistence,
    )

    job = await runner.run_suite("independent-suite")
    assert job.case_results[0].status is EvalCaseStatus.ERROR
    assert (job.passed_count, job.failed_count, job.error_count) == (0, 0, 1)
    database_bytes = database_path.read_bytes()
    assert b"RAW_PROVIDER_SENTINEL" not in database_bytes
    assert b"TRACEBACK_SENTINEL" not in database_bytes
    assert b"MODEL_STRUCTURED_OUTPUT_INVALID" in database_bytes


@pytest.mark.asyncio
async def test_malformed_tool_result_does_not_persist_raw_tool_payload(
    tmp_path: Path,
) -> None:
    """A malformed adapter payload is normalized before eval persistence."""

    async def malformed_handler(
        request: WorkOrderQueryRequest,
    ) -> WorkOrderQueryResponse:
        return cast(
            WorkOrderQueryResponse,
            {
                "result_status": "found",
                "work_order_id": request.work_order_id,
                "raw_tool_payload": "RAW_TOOL_SENTINEL",
            },
        )

    registry = ToolRegistry(
        [
            RegisteredTool(
                spec=ToolSpec(
                    name="malformed_query",
                    description="independent malformed-result capability",
                    mode=ToolMode.READ_ONLY,
                ),
                request_model=WorkOrderQueryRequest,
                response_model=WorkOrderQueryResponse,
                handler=malformed_handler,
            )
        ]
    )
    runtime, _ = _queued_runtime(
        [
            _understanding(),
            ActionDecisionOutput(
                action=AgentAction.SEARCH,
                goal="inspect",
                rationale="test tool result boundary",
            ),
            {
                "selected_tool": "malformed_query",
                "arguments": {"work_order_id": "WO20260001"},
                "expected_resolution": "test",
            },
            {
                "evidence_sufficient": False,
                "summary": "tool result failed validation",
                "confirmed_facts": [],
                "unresolved_questions": [],
                "recommended_action": "END_CONVERSATION",
            },
            ActionDecisionOutput(
                action=AgentAction.END_CONVERSATION,
                goal="close",
                rationale="safe failure observation",
            ),
        ],
    )
    runtime = OpsAgentRuntime(runtime.gateway, registry)
    loader = _write_suite(
        tmp_path / "malformed-tool-suite.json",
        _suite_payload(
            assertions=[
                {
                    "assertion_id": "action",
                    "type": "final_action_in",
                    "expected": ["END_CONVERSATION"],
                }
            ]
        ),
    )
    database_path = tmp_path / "opsmind.db"
    run_repository = SQLiteRunRepository(database_path)
    execution_service = AgentExecutionService(
        runtime,
        RunPersistenceService(run_repository, app_version="tester"),
    )
    eval_repository = SQLiteEvalRepository(database_path)
    persistence = EvalPersistenceService(
        eval_repository,
        app_version="tester",
        run_repository=run_repository,
    )
    runner = EvalRunner(
        loader=loader,
        execution_service=execution_service,
        persistence=persistence,
    )

    job = await runner.run_suite("independent-suite")

    assert job.lifecycle_status is EvalJobLifecycleStatus.COMPLETED
    assert job.case_results[0].status is EvalCaseStatus.PASS
    stored_run = run_repository.get(job.case_runs[0].run_id)
    assert stored_run is not None
    assert all(step.summary != "RAW_TOOL_SENTINEL" for step in stored_run.steps)
    assert b"RAW_TOOL_SENTINEL" not in database_path.read_bytes()


def test_eval_finalization_rolls_back_terminal_and_child_rows_together(
    tmp_path: Path,
) -> None:
    """A child-row failure must not leave a terminal parent or partial rows."""

    database_path = tmp_path / "opsmind.db"
    run_repository = SQLiteRunRepository(database_path)
    run_service = RunPersistenceService(run_repository, app_version="tester")
    active_run = run_service.start(
        request_id="request-for-eval",
        thread_id="thread-for-eval",
        input_message="run",
        source_context={"channel": "tester"},
    )
    run_service.fail(active_run, error_code="MODEL_INVOCATION_FAILED")
    eval_repository = SQLiteEvalRepository(database_path)
    persistence = EvalPersistenceService(
        eval_repository,
        app_version="tester",
        run_repository=run_repository,
    )
    active_job = persistence.start(
        suite_id="independent-suite",
        suite_version="1.0",
        case_count=1,
        runtime_identity="mock",
    )
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """CREATE TRIGGER reject_eval_assertion BEFORE INSERT
               ON eval_assertion_results
               BEGIN SELECT RAISE(ABORT, 'injected eval failure'); END"""
        )

    with pytest.raises(EvalPersistenceError):
        persistence.complete(
            active_job,
            case_results=[
                _case_result(active_job.eval_job_id, run_id=active_run.run_id)
            ],
        )

    stored = eval_repository.get(active_job.eval_job_id)
    assert stored is not None
    assert stored.lifecycle_status is EvalJobLifecycleStatus.STARTED
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM eval_case_results WHERE eval_job_id = ?",
            (active_job.eval_job_id,),
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT COUNT(*) FROM eval_assertion_results WHERE eval_job_id = ?",
            (active_job.eval_job_id,),
        ).fetchone() == (0,)


def test_malformed_stored_eval_json_returns_safe_integrity_error(
    tmp_path: Path,
) -> None:
    """Corrupt eval snapshots must fail closed without reflecting their text."""

    database_path = tmp_path / "opsmind.db"
    run_repository = SQLiteRunRepository(database_path)
    run_service = RunPersistenceService(run_repository, app_version="tester")
    active_run = run_service.start(
        request_id="request-for-corruption",
        thread_id="thread-for-corruption",
        input_message="run",
        source_context={"channel": "tester"},
    )
    run_service.fail(active_run, error_code="MODEL_INVOCATION_FAILED")
    eval_repository = SQLiteEvalRepository(database_path)
    persistence = EvalPersistenceService(
        eval_repository,
        app_version="tester",
        run_repository=run_repository,
    )
    active_job = persistence.start(
        suite_id="independent-suite",
        suite_version="1.0",
        case_count=1,
        runtime_identity="mock",
    )
    completed = persistence.complete(
        active_job,
        case_results=[
            _case_result(active_job.eval_job_id, run_id=active_run.run_id)
        ],
    )
    sentinel = "RAW_CORRUPT_EVAL_JSON_SENTINEL"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "UPDATE eval_case_results SET run_ids_json = ? "
            "WHERE eval_job_id = ?",
            (f'["{sentinel}"', completed.eval_job_id),
        )

    with pytest.raises(EvalDataIntegrityError) as captured:
        eval_repository.get(completed.eval_job_id)
    assert sentinel not in str(captured.value)


def test_eval_schema_addition_preserves_existing_run_schema_v1_and_run_reads(
    tmp_path: Path,
) -> None:
    """Eval initialization must leave an existing P1-007 run readable."""

    database_path = tmp_path / "opsmind.db"
    run_repository = SQLiteRunRepository(database_path)
    run_service = RunPersistenceService(run_repository, app_version="tester")
    active = run_service.start(
        request_id="request-existing",
        thread_id="thread-existing",
        input_message="existing run",
        source_context={"channel": "tester"},
    )
    run_service.fail(active, error_code="MODEL_INVOCATION_FAILED")

    eval_repository = SQLiteEvalRepository(database_path)
    assert eval_repository.list(limit=1) == []
    existing = run_repository.get(active.run_id)
    assert existing is not None
    assert existing.run_id == active.run_id
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT value FROM schema_metadata WHERE key = 'schema_version'"
        ).fetchone() == ("1",)
        assert connection.execute(
            "SELECT value FROM eval_schema_metadata WHERE key = 'eval_schema_version'"
        ).fetchone() == ("1",)
