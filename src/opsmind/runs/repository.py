"""Repository boundary for Agent-run persistence."""

from __future__ import annotations

from typing import Protocol

from opsmind.runs.models import AgentRun, AgentRunSummary


class RunPersistenceError(RuntimeError):
    """Safe boundary error for unavailable or inconsistent run persistence."""


class IncompatibleRunSchemaError(RunPersistenceError):
    """Raised when an existing database cannot be read as the current schema."""


class RunAlreadyExistsError(RunPersistenceError):
    """Raised when a run or request identifier is already persisted."""


class RunNotFoundError(LookupError):
    """Raised only for a valid lookup of an unknown run identifier."""


class RunStateConflictError(RunPersistenceError):
    """Raised when a lifecycle transition is missing, repeated, or invalid."""


class RunDataIntegrityError(RunPersistenceError):
    """Raised when persisted typed snapshots fail validation on read."""


class RunRepository(Protocol):
    """Backend-neutral transactional storage contract."""

    def create_started(self, run: AgentRun) -> None:
        """Persist exactly one new STARTED run."""

    def finalize_succeeded(
        self,
        *,
        run: AgentRun,
    ) -> None:
        """Atomically write the successful terminal record and child rows."""

    def finalize_failed(
        self,
        *,
        run: AgentRun,
    ) -> None:
        """Atomically write a normalized failed record and safe failure steps."""

    def get(self, run_id: str) -> AgentRun | None:
        """Return one fully validated run or ``None`` when it is absent."""

    def list(self, *, limit: int) -> list[AgentRunSummary]:
        """Return newest runs first, bounded by ``limit``."""


__all__ = [
    "IncompatibleRunSchemaError",
    "RunAlreadyExistsError",
    "RunDataIntegrityError",
    "RunNotFoundError",
    "RunPersistenceError",
    "RunRepository",
    "RunStateConflictError",
]
