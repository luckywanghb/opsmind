"""Safe projection and lifecycle service above the repository boundary."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter
from uuid import uuid4

from pydantic import JsonValue

from opsmind.agent.grounding import stable_evidence_items
from opsmind.models import ModelProfile
from opsmind.runs.models import (
    MAX_SAFE_CONTEXT_VALUE_LENGTH,
    AgentRun,
    AgentRunSummary,
    AgentTerminalStatus,
    RunLifecycleStatus,
    RunStep,
    RuntimeMetadata,
    SafeSourceContext,
)
from opsmind.runs.repository import RunNotFoundError, RunRepository
from opsmind.state import DecisionState, EvidenceItem, HandoffState, UnderstandingState

UtcClock = Callable[[], datetime]
MonotonicClock = Callable[[], float]


@dataclass(frozen=True, slots=True)
class ActiveRun:
    """Request-local token holding only safe start state and monotonic timing."""

    started: AgentRun
    monotonic_started: float

    @property
    def run_id(self) -> str:
        return self.started.run_id


def _safe_context_value(value: JsonValue | None) -> str | None:
    if not isinstance(value, str) or len(value) > MAX_SAFE_CONTEXT_VALUE_LENGTH:
        return None
    return value


class RunPersistenceService:
    """Own run IDs, safe projections, timing, and repository transitions."""

    def __init__(
        self,
        repository: RunRepository,
        *,
        app_version: str,
        build_sha: str | None = None,
        utc_now: UtcClock | None = None,
        monotonic: MonotonicClock | None = None,
    ) -> None:
        self._repository = repository
        self._app_version = app_version
        self._build_sha = build_sha
        self._utc_now = utc_now or (lambda: datetime.now(UTC))
        self._monotonic = monotonic or perf_counter

    def start(
        self,
        *,
        request_id: str,
        thread_id: str,
        input_message: str,
        source_context: Mapping[str, JsonValue],
    ) -> ActiveRun:
        """Create the durable STARTED record before Agent execution begins."""

        monotonic_started = self._monotonic()
        started_at = self._utc_now()
        run = AgentRun(
            run_id=str(uuid4()),
            request_id=request_id,
            thread_id=thread_id,
            lifecycle_status=RunLifecycleStatus.STARTED,
            input_message=input_message,
            source_context=SafeSourceContext(
                channel=_safe_context_value(source_context.get("channel")),
                user_id=_safe_context_value(source_context.get("user_id")),
                site_id=_safe_context_value(source_context.get("site_id")),
            ),
            started_at=started_at,
            runtime_metadata=self._metadata(()),
        )
        self._repository.create_started(run)
        return ActiveRun(started=run, monotonic_started=monotonic_started)

    def succeed(
        self,
        active: ActiveRun,
        *,
        terminal_status: AgentTerminalStatus,
        understanding: UnderstandingState,
        decision: DecisionState,
        final_reply: str | None,
        handoff: HandoffState | None,
        steps: Sequence[RunStep],
        evidence: Sequence[EvidenceItem],
    ) -> AgentRun:
        """Atomically finalize one success using safe typed projections only."""

        stable_evidence = stable_evidence_items(evidence)
        terminal = active.started.model_copy(
            update={
                "lifecycle_status": RunLifecycleStatus.SUCCEEDED,
                "agent_terminal_status": terminal_status,
                "understanding": UnderstandingState.model_validate(understanding),
                "decision": DecisionState.model_validate(decision),
                "final_reply": final_reply,
                "handoff": (
                    HandoffState.model_validate(handoff)
                    if handoff is not None
                    else None
                ),
                "completed_at": self._utc_now(),
                "duration_ms": self._duration_ms(active),
                "runtime_metadata": self._metadata(steps),
                "steps": list(steps),
                "evidence": stable_evidence,
            }
        )
        canonical = AgentRun.model_validate(terminal)
        self._repository.finalize_succeeded(run=canonical)
        return canonical

    def fail(
        self,
        active: ActiveRun,
        *,
        error_code: str,
        steps: Sequence[RunStep] = (),
    ) -> AgentRun:
        """Atomically finalize one failure with a normalized code only."""

        terminal = active.started.model_copy(
            update={
                "lifecycle_status": RunLifecycleStatus.FAILED,
                "completed_at": self._utc_now(),
                "duration_ms": self._duration_ms(active),
                "error_code": error_code,
                "runtime_metadata": self._metadata(steps),
                "steps": list(steps),
            }
        )
        canonical = AgentRun.model_validate(terminal)
        self._repository.finalize_failed(run=canonical)
        return canonical

    def get(self, run_id: str) -> AgentRun:
        run = self._repository.get(run_id)
        if run is None:
            raise RunNotFoundError(run_id)
        return run

    def list(self, *, limit: int) -> list[AgentRunSummary]:
        return list(self._repository.list(limit=limit))

    def _duration_ms(self, active: ActiveRun) -> float:
        return max(0.0, (self._monotonic() - active.monotonic_started) * 1_000)

    def _metadata(self, steps: Sequence[RunStep]) -> RuntimeMetadata:
        profiles: list[ModelProfile] = []
        for step in steps:
            if isinstance(step.profile, ModelProfile) and step.profile not in profiles:
                profiles.append(step.profile)
        return RuntimeMetadata(
            app_version=self._app_version,
            build_sha=self._build_sha,
            logical_model_profiles=profiles,
        )
