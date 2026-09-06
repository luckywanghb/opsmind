"""Backend-neutral persistence contracts for evaluation jobs."""

from __future__ import annotations

from typing import Protocol

from opsmind.evals.models import EvalJob, EvalJobSummary


class EvalPersistenceError(RuntimeError):
    """Safe boundary error for unavailable or inconsistent eval persistence."""


class IncompatibleEvalSchemaError(EvalPersistenceError):
    """Raised when eval tables are missing or use an unsupported version."""


class EvalNotFoundError(LookupError):
    """Raised only for a valid lookup of an unknown eval job."""


class EvalStateConflictError(EvalPersistenceError):
    """Raised when an eval lifecycle transition is invalid or repeated."""


class EvalDataIntegrityError(EvalPersistenceError):
    """Raised when persisted eval JSON cannot be validated safely."""


class EvalRepository(Protocol):
    """Transactional storage contract for eval jobs and child results."""

    def create_started(self, job: EvalJob) -> None:
        """Persist exactly one STARTED job."""

    def finalize_completed(self, *, job: EvalJob) -> None:
        """Atomically persist a completed job and all result rows."""

    def finalize_failed(self, *, job: EvalJob) -> None:
        """Persist a fatal FAILED job without quality results."""

    def get(self, eval_job_id: str) -> EvalJob | None:
        """Return one fully validated job or ``None`` when absent."""

    def list(self, *, limit: int) -> list[EvalJobSummary]:
        """Return newest jobs first, bounded by ``limit``."""


__all__ = [
    "EvalDataIntegrityError",
    "EvalNotFoundError",
    "EvalPersistenceError",
    "EvalRepository",
    "EvalStateConflictError",
    "IncompatibleEvalSchemaError",
]
