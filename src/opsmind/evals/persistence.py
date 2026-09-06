"""Safe lifecycle service above the evaluation repository boundary."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter
from uuid import uuid4

from opsmind.evals.models import (
    EvalCaseResult,
    EvalCaseRun,
    EvalJob,
    EvalJobLifecycleStatus,
    EvalJobSummary,
)
from opsmind.evals.repository import (
    EvalNotFoundError,
    EvalPersistenceError,
    EvalRepository,
)
from opsmind.runs import RunRepository

UtcClock = Callable[[], datetime]
MonotonicClock = Callable[[], float]


@dataclass(frozen=True, slots=True)
class ActiveEvalJob:
    started: EvalJob
    monotonic_started: float

    @property
    def eval_job_id(self) -> str:
        return self.started.eval_job_id


class EvalPersistenceService:
    """Own eval IDs, result counts, run references, and lifecycle transitions."""

    def __init__(
        self,
        repository: EvalRepository,
        *,
        app_version: str,
        build_sha: str | None = None,
        run_repository: RunRepository | None = None,
        utc_now: UtcClock | None = None,
        monotonic: MonotonicClock | None = None,
    ) -> None:
        self._repository = repository
        self._app_version = app_version
        self._build_sha = build_sha
        self._run_repository = run_repository
        self._utc_now = utc_now or (lambda: datetime.now(UTC))
        self._monotonic = monotonic or perf_counter

    def start(
        self,
        *,
        suite_id: str,
        suite_version: str,
        case_count: int,
        runtime_identity: str,
    ) -> ActiveEvalJob:
        started = EvalJob(
            eval_job_id=str(uuid4()),
            suite_id=suite_id,
            suite_version=suite_version,
            lifecycle_status=EvalJobLifecycleStatus.STARTED,
            case_count=case_count,
            passed_count=0,
            failed_count=0,
            error_count=0,
            started_at=self._utc_now(),
            app_version=self._app_version,
            build_sha=self._build_sha,
            runtime_identity=runtime_identity,
        )
        monotonic_started = self._monotonic()
        self._repository.create_started(started)
        return ActiveEvalJob(started=started, monotonic_started=monotonic_started)

    def complete(
        self,
        active: ActiveEvalJob,
        *,
        case_results: Sequence[EvalCaseResult],
    ) -> EvalJob:
        results = [EvalCaseResult.model_validate(item) for item in case_results]
        if len(results) != active.started.case_count:
            raise EvalPersistenceError("eval case count does not match suite")
        if len({item.case_id for item in results}) != len(results):
            raise EvalPersistenceError("eval case IDs are not unique")
        for item in results:
            if item.eval_job_id != active.eval_job_id:
                raise EvalPersistenceError("eval case references a different job")
            for run_id in item.run_ids:
                if self._run_repository is None:
                    continue
                try:
                    run = self._run_repository.get(run_id)
                except Exception as exc:
                    raise EvalPersistenceError(
                        "Agent run reference unavailable"
                    ) from exc
                if run is None:
                    raise EvalPersistenceError("Agent run reference is unknown")
        passed = sum(item.status.value == "PASS" for item in results)
        failed = sum(item.status.value == "FAIL" for item in results)
        errors = sum(item.status.value == "ERROR" for item in results)
        completed_at = self._utc_now()
        terminal = active.started.model_copy(
            update={
                "lifecycle_status": EvalJobLifecycleStatus.COMPLETED,
                "passed_count": passed,
                "failed_count": failed,
                "error_count": errors,
                "completed_at": completed_at,
                "duration_ms": self._duration_ms(active),
                "case_results": results,
                "case_runs": [
                    EvalCaseRun(
                        eval_job_id=active.eval_job_id,
                        case_id=item.case_id,
                        turn_index=turn_index,
                        run_id=run_id,
                    )
                    for item in results
                    for turn_index, run_id in enumerate(item.run_ids)
                ],
            }
        )
        canonical = EvalJob.model_validate(terminal)
        self._repository.finalize_completed(job=canonical)
        return canonical

    def fail(self, active: ActiveEvalJob, *, error_code: str) -> EvalJob:
        terminal = active.started.model_copy(
            update={
                "lifecycle_status": EvalJobLifecycleStatus.FAILED,
                "completed_at": self._utc_now(),
                "duration_ms": self._duration_ms(active),
                "error_code": error_code,
            }
        )
        canonical = EvalJob.model_validate(terminal)
        self._repository.finalize_failed(job=canonical)
        return canonical

    def get(self, eval_job_id: str) -> EvalJob:
        job = self._repository.get(eval_job_id)
        if job is None:
            raise EvalNotFoundError(eval_job_id)
        return job

    def list(self, *, limit: int) -> list[EvalJobSummary]:
        return list(self._repository.list(limit=limit))

    def _duration_ms(self, active: ActiveEvalJob) -> float:
        return max(0.0, (self._monotonic() - active.monotonic_started) * 1_000)


__all__ = ["ActiveEvalJob", "EvalPersistenceService"]
