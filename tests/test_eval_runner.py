from __future__ import annotations

import json
from pathlib import Path

from opsmind.agent.schemas import ActionDecisionOutput, RequestUnderstandingOutput
from opsmind.api.runtime import OpsAgentRuntime
from opsmind.conversations import (
    ConversationPersistenceService,
    SQLiteConversationRepository,
)
from opsmind.evals import (
    EvalJobLifecycleStatus,
    EvalPersistenceService,
    EvalRunner,
    EvalSuiteLoader,
    EvaluatorRegistry,
    SQLiteEvalRepository,
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
from opsmind.state import AgentAction, PrimaryIntent, RequestType, RiskSignal


def _understanding() -> RequestUnderstandingOutput:
    return RequestUnderstandingOutput(
        primary_intent=PrimaryIntent.WORKFLOW_ISSUE,
        request_type=RequestType.DIAGNOSE,
        symptom="test",
        entities={},
        risk_signal=RiskSignal.NONE,
        uncertainty=None,
    )


def _gateway(responses: list[object]) -> tuple[OpsAgentRuntime, MockModelProvider]:
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
    return OpsAgentRuntime(gateway), provider


def _suite(
    path: Path,
    *,
    turns: list[str],
    assertions: list[dict[str, object]],
    evaluator_registry: EvaluatorRegistry | None = None,
) -> EvalSuiteLoader:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "suite_id": "test-suite",
                "suite_version": "1.0",
                "description": "runner test suite",
                "cases": [
                    {
                        "case_id": "C1",
                        "title": "runner case",
                        "turns": [{"message": message} for message in turns],
                        "source_context": {"channel": "eval"},
                        "assertions": assertions,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return EvalSuiteLoader(path, evaluator_registry=evaluator_registry)


def _runner(
    tmp_path: Path,
    responses: list[object],
    loader: EvalSuiteLoader,
    *,
    evaluators: EvaluatorRegistry | None = None,
) -> tuple[EvalRunner, MockModelProvider, SQLiteRunRepository]:
    runtime, provider = _gateway(responses)
    run_repository = SQLiteRunRepository(tmp_path / "opsmind.db")
    execution = AgentExecutionService(
        runtime,
        RunPersistenceService(run_repository, app_version="test"),
        conversation_persistence=ConversationPersistenceService(
            SQLiteConversationRepository(tmp_path / "opsmind.db")
        ),
    )
    eval_repository = SQLiteEvalRepository(tmp_path / "opsmind.db")
    persistence = EvalPersistenceService(
        eval_repository,
        app_version="test",
        run_repository=run_repository,
    )
    return (
        EvalRunner(
            loader=loader,
            execution_service=execution,
            persistence=persistence,
            evaluators=evaluators,
        ),
        provider,
        run_repository,
    )


def test_runner_single_turn_pass_and_real_run_link(tmp_path: Path) -> None:
    loader = _suite(
        tmp_path / "suite.json",
        turns=["done"],
        assertions=[
            {
                "assertion_id": "lifecycle",
                "type": "run_lifecycle_succeeded",
                "expected": True,
            },
            {
                "assertion_id": "terminal",
                "type": "final_action_in",
                "expected": ["END_CONVERSATION"],
            },
        ],
    )
    runner, _, run_repository = _runner(
        tmp_path,
        [
            _understanding(),
            ActionDecisionOutput(
                action=AgentAction.END_CONVERSATION,
                goal="close",
                rationale="done",
            ),
        ],
        loader,
    )

    job = __import__("asyncio").run(runner.run_suite("test-suite"))

    assert job.lifecycle_status is EvalJobLifecycleStatus.COMPLETED
    assert job.passed_count == 1
    assert job.failed_count == 0
    assert job.case_results[0].status.value == "PASS"
    assert len(job.case_runs) == 1
    assert run_repository.get(job.case_runs[0].run_id) is not None


def test_runner_quality_fail_does_not_fail_job(tmp_path: Path) -> None:
    loader = _suite(
        tmp_path / "suite.json",
        turns=["done"],
        assertions=[
            {
                "assertion_id": "mismatch",
                "type": "final_action_in",
                "expected": ["REPLY"],
            }
        ],
    )
    runner, _, _ = _runner(
        tmp_path,
        [
            _understanding(),
            ActionDecisionOutput(
                action=AgentAction.END_CONVERSATION,
                goal="close",
                rationale="done",
            ),
        ],
        loader,
    )

    job = __import__("asyncio").run(runner.run_suite("test-suite"))

    assert job.lifecycle_status is EvalJobLifecycleStatus.COMPLETED
    assert job.passed_count == 0
    assert job.failed_count == 1
    assert job.error_count == 0
    assert job.case_results[0].status.value == "FAIL"


def test_invalid_registered_evaluator_result_is_case_error_and_job_completes(
    tmp_path: Path,
) -> None:
    def invalid_evaluator(assertion: object, context: object) -> object:
        return {"invalid": "result"}

    registry = EvaluatorRegistry({"invalid": invalid_evaluator})  # type: ignore[arg-type]
    loader = _suite(
        tmp_path / "suite.json",
        turns=["done"],
        assertions=[
            {
                "assertion_id": "invalid-result",
                "type": "invalid",
                "expected": True,
            }
        ],
        evaluator_registry=registry,
    )
    runner, _, _ = _runner(
        tmp_path,
        [
            _understanding(),
            ActionDecisionOutput(
                action=AgentAction.END_CONVERSATION,
                goal="close",
                rationale="done",
            ),
        ],
        loader,
        evaluators=registry,
    )

    job = __import__("asyncio").run(runner.run_suite("test-suite"))

    assert job.lifecycle_status is EvalJobLifecycleStatus.COMPLETED
    assert job.passed_count == 0
    assert job.failed_count == 0
    assert job.error_count == 1
    assert job.case_results[0].status.value == "ERROR"
    assert job.case_results[0].error_code == "EVAL_ASSERTION_ERROR"
    assert job.case_results[0].assertions[0].status.value == "ERROR"


def test_runner_runtime_error_is_case_error_and_job_completes(tmp_path: Path) -> None:
    loader = _suite(
        tmp_path / "suite.json",
        turns=["done"],
        assertions=[
            {
                "assertion_id": "lifecycle",
                "type": "run_lifecycle_succeeded",
                "expected": True,
            }
        ],
    )
    runner, _, run_repository = _runner(
        tmp_path,
        [ModelStructuredOutputError("RAW_PROVIDER_SENTINEL")],
        loader,
    )

    job = __import__("asyncio").run(runner.run_suite("test-suite"))

    assert job.lifecycle_status is EvalJobLifecycleStatus.COMPLETED
    assert job.error_count == 1
    assert job.case_results[0].status.value == "ERROR"
    assert job.case_results[0].error_code == "MODEL_STRUCTURED_OUTPUT_INVALID"
    assert len(job.case_runs) == 1
    failed_run = run_repository.get(job.case_runs[0].run_id)
    assert failed_run is not None
    assert failed_run.error_code == "MODEL_STRUCTURED_OUTPUT_INVALID"


def test_runner_multiturn_reuses_thread_and_restores_bounded_context(
    tmp_path: Path,
) -> None:
    loader = _suite(
        tmp_path / "suite.json",
        turns=["first", "second"],
        assertions=[
            {
                "assertion_id": "identity",
                "type": "same_thread_across_turns",
                "expected": True,
            }
        ],
    )
    responses = [
        _understanding(),
        ActionDecisionOutput(
            action=AgentAction.END_CONVERSATION, goal="close", rationale="one"
        ),
        _understanding(),
        ActionDecisionOutput(
            action=AgentAction.END_CONVERSATION, goal="close", rationale="two"
        ),
    ]
    runner, provider, _ = _runner(tmp_path, responses, loader)

    job = __import__("asyncio").run(runner.run_suite("test-suite"))

    assert job.case_results[0].status.value == "PASS"
    assert len(job.case_runs) == 2
    assert job.case_runs[0].run_id != job.case_runs[1].run_id
    assert provider.history[2].messages[1].content.find("second") >= 0
    second_context = json.loads(provider.history[2].messages[1].content)
    assert second_context["original_query"] == "first"
    assert second_context["recent_turns"] == [
        {"role": "USER", "content": "first"}
    ]
