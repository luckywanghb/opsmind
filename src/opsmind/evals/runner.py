"""Synchronous-invocation boundary for repeatable Golden Suite runs."""

from __future__ import annotations

from datetime import UTC, datetime
from time import perf_counter
from uuid import uuid4

from opsmind.evals.evaluators import CaseEvaluationContext, EvaluatorRegistry
from opsmind.evals.loader import EvalSuiteLoader, EvalSuiteLoadError
from opsmind.evals.models import (
    EvalCase,
    EvalCaseResult,
    EvalCaseStatus,
    EvalJob,
    EvaluationObservation,
)
from opsmind.evals.persistence import ActiveEvalJob, EvalPersistenceService
from opsmind.evals.repository import EvalPersistenceError
from opsmind.execution import AgentExecutionError, AgentExecutionService


class EvalRunnerError(RuntimeError):
    """Fatal runner failure distinct from an individual case quality failure."""


class EvalRunner:
    """Run each suite turn through the same execution service as Chat."""

    def __init__(
        self,
        *,
        loader: EvalSuiteLoader,
        execution_service: AgentExecutionService,
        persistence: EvalPersistenceService,
        evaluators: EvaluatorRegistry | None = None,
    ) -> None:
        self._loader = loader
        self._execution_service = execution_service
        self._persistence = persistence
        self._evaluators = evaluators or EvaluatorRegistry()

    @property
    def evaluators(self) -> EvaluatorRegistry:
        return self._evaluators

    async def run_suite(self, suite_id: str | None = None) -> EvalJob:
        """Load one immutable suite, execute it, and persist its result."""

        suite = self._loader.load()
        if suite_id is not None and suite.suite_id != suite_id:
            raise EvalSuiteLoadError("requested eval suite is unavailable")
        runtime_identity = self._runtime_identity()
        try:
            active = self._persistence.start(
                suite_id=suite.suite_id,
                suite_version=suite.suite_version,
                case_count=len(suite.cases),
                runtime_identity=runtime_identity,
            )
        except EvalPersistenceError:
            raise
        results: list[EvalCaseResult] = []
        try:
            for case in suite.cases:
                results.append(await self._run_case(active, case))
            return self._persistence.complete(active, case_results=results)
        except EvalPersistenceError:
            raise
        except Exception as exc:
            # This is an infrastructure failure, not a product-quality FAIL.
            try:
                self._persistence.fail(
                    active,
                    error_code="EVAL_RUNNER_FAILED",
                )
            except EvalPersistenceError as persistence_error:
                raise persistence_error from None
            raise EvalRunnerError("eval runner failed") from exc

    async def _run_case(
        self,
        active: ActiveEvalJob,
        case: EvalCase,
    ) -> EvalCaseResult:
        started_at = datetime.now(UTC)
        monotonic_started = perf_counter()
        observations: list[EvaluationObservation] = []
        run_ids: list[str] = []
        thread_id = str(uuid4())
        error_code: str | None = None
        for turn in case.turns:
            request_id = str(uuid4())
            source_context = dict(case.source_context)
            if turn.source_context is not None:
                source_context.update(turn.source_context)
            try:
                result = await self._execution_service.execute(
                    message=turn.message,
                    source_context=source_context,
                    request_id=request_id,
                    thread_id=thread_id,
                )
            except AgentExecutionError as exc:
                # The shared service has already persisted the real failed
                # AgentRun.  Keep the relation and mark only this case ERROR.
                run_ids.append(exc.run_id)
                error_code = exc.error_code
                break
            run_ids.append(result.run_id)
            observations.append(result.evaluation_observation)

        if error_code is not None:
            return EvalCaseResult(
                eval_job_id=active.eval_job_id,
                case_id=case.case_id,
                title=case.title,
                status=EvalCaseStatus.ERROR,
                known_gap=case.known_gap,
                run_ids=run_ids,
                assertions=[],
                started_at=started_at,
                completed_at=datetime.now(UTC),
                duration_ms=max(0.0, (perf_counter() - monotonic_started) * 1_000),
                error_code=error_code,
            )

        context = CaseEvaluationContext(observations=tuple(observations))
        assertion_results = [
            self._evaluators.evaluate(assertion, context)
            for assertion in case.assertions
        ]
        if any(item.status.value == "ERROR" for item in assertion_results):
            status = EvalCaseStatus.ERROR
            case_error = "EVAL_ASSERTION_ERROR"
        elif any(
            item.blocking and item.status.value == "FAIL" for item in assertion_results
        ):
            status = EvalCaseStatus.FAIL
            case_error = None
        else:
            status = EvalCaseStatus.PASS
            case_error = None
        return EvalCaseResult(
            eval_job_id=active.eval_job_id,
            case_id=case.case_id,
            title=case.title,
            status=status,
            known_gap=case.known_gap,
            run_ids=run_ids,
            assertions=assertion_results,
            started_at=started_at,
            completed_at=datetime.now(UTC),
            duration_ms=max(0.0, (perf_counter() - monotonic_started) * 1_000),
            error_code=case_error,
        )

    def _runtime_identity(self) -> str:
        routes = self._execution_service.runtime.gateway.routes
        providers = sorted({route.provider for route in routes.values()})
        if not providers:
            return "unconfigured"
        return ",".join(providers)


__all__ = ["EvalRunner", "EvalRunnerError"]
