"""Typed contracts for the backend-owned OpsMind evaluation domain."""

from __future__ import annotations

import math
from datetime import datetime
from enum import StrEnum
from typing import Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

from opsmind.state import (
    AgentAction,
    DecisionState,
    EvidenceItem,
    FiniteJsonObject,
    HandoffState,
    LoopState,
    TaskStatus,
    UnderstandingState,
)

MAX_SUITE_DESCRIPTION_LENGTH = 2_000
MAX_CASE_TITLE_LENGTH = 256
MAX_CASE_NOTES_LENGTH = 2_000
MAX_ASSERTION_MESSAGE_LENGTH = 512
MAX_SAFE_ASSERTION_VALUE_LENGTH = 512
MAX_SAFE_ASSERTION_VALUE_ITEMS = 32
MAX_EVAL_JSON_NESTING_DEPTH = 32


def _finite_json(value: object, path: str = "$") -> None:
    """Reject non-finite, oversized, or deeply nested eval JSON values.

    This intentionally uses an explicit work list.  Suite content is
    attacker-controlled at the loader boundary, so recursive validation must
    not be able to turn malformed input into a raw ``RecursionError``.
    """

    pending: list[tuple[object, str, int]] = [(value, path, 0)]
    while pending:
        current, current_path, depth = pending.pop()
        if depth > MAX_EVAL_JSON_NESTING_DEPTH:
            raise ValueError(
                f"JSON value at {current_path} is nested too deeply"
            )
        if isinstance(current, float) and not math.isfinite(current):
            raise ValueError(f"non-finite JSON value at {current_path}")
        if isinstance(current, str):
            if len(current) > MAX_SAFE_ASSERTION_VALUE_LENGTH:
                raise ValueError(f"JSON string at {current_path} is too long")
            continue
        if isinstance(current, list):
            if len(current) > MAX_SAFE_ASSERTION_VALUE_ITEMS:
                raise ValueError(f"JSON list at {current_path} is too large")
            pending.extend(
                (item, f"{current_path}[{index}]", depth + 1)
                for index, item in reversed(list(enumerate(current)))
            )
            continue
        if isinstance(current, dict):
            if len(current) > MAX_SAFE_ASSERTION_VALUE_ITEMS:
                raise ValueError(f"JSON object at {current_path} is too large")
            children: list[tuple[object, str, int]] = []
            for key, item in reversed(list(current.items())):
                if not isinstance(key, str):
                    raise ValueError(f"JSON key at {current_path} is not text")
                if len(key) > MAX_SAFE_ASSERTION_VALUE_LENGTH:
                    raise ValueError(f"JSON key at {current_path} is too long")
                children.append((item, f"{current_path}.{key}", depth + 1))
            pending.extend(children)


def _validate_json_depth(value: object, path: str = "$") -> None:
    """Check suite-wide JSON depth without applying field-specific limits."""

    pending: list[tuple[object, str, int]] = [(value, path, 0)]
    while pending:
        current, current_path, depth = pending.pop()
        if depth > MAX_EVAL_JSON_NESTING_DEPTH:
            raise ValueError(
                f"JSON value at {current_path} is nested too deeply"
            )
        if isinstance(current, float) and not math.isfinite(current):
            raise ValueError(f"non-finite JSON value at {current_path}")
        if isinstance(current, list):
            pending.extend(
                (item, f"{current_path}[{index}]", depth + 1)
                for index, item in reversed(list(enumerate(current)))
            )
        elif isinstance(current, dict):
            for key, item in reversed(list(current.items())):
                if not isinstance(key, str):
                    raise ValueError(f"JSON key at {current_path} is not text")
                pending.append((item, f"{current_path}.{key}", depth + 1))


class EvalModelMixin(BaseModel):
    """Strict, revalidating base for persisted and loaded eval records."""

    model_config = ConfigDict(extra="forbid", revalidate_instances="always")


class EvalJobLifecycleStatus(StrEnum):
    STARTED = "STARTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class EvalCaseStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"


class EvalAssertionStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"


class EvalTurn(EvalModelMixin):
    """One user turn in a Golden Case."""

    message: str = Field(min_length=1, max_length=8_000)
    source_context: FiniteJsonObject | None = None

    @field_validator("message")
    @classmethod
    def reject_blank_message(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("eval turn message must not be blank")
        return value


class ToolCallObservation(EvalModelMixin):
    """Safe validated tool-call metadata exposed only to evaluators."""

    tool_name: str = Field(min_length=1, max_length=128)
    arguments: FiniteJsonObject = Field(default_factory=dict)
    status: str = Field(min_length=1, max_length=64)
    error_code: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def validate_size(self) -> Self:
        _finite_json(self.arguments)
        if len(self.model_dump_json().encode("utf-8")) > 16 * 1_024:
            raise ValueError("tool observation is too large")
        return self


class EvaluationObservation(EvalModelMixin):
    """Safe internal observation for one successful Agent execution.

    It intentionally contains no prompt, model response, hidden reasoning, or
    raw adapter result.  The runner consumes it transiently and persists only
    assertion outcomes.
    """

    run_id: str = Field(min_length=1, max_length=128)
    request_id: str = Field(min_length=1, max_length=128)
    thread_id: str = Field(min_length=1, max_length=128)
    lifecycle_status: str = Field(min_length=1, max_length=32)
    understanding: UnderstandingState
    final_decision: DecisionState
    action_sequence: list[AgentAction] = Field(default_factory=list, max_length=64)
    tool_calls: list[ToolCallObservation] = Field(default_factory=list, max_length=64)
    loop: LoopState
    evidence: list[EvidenceItem] = Field(default_factory=list, max_length=50)
    handoff: HandoffState
    terminal_status: TaskStatus | str = Field(min_length=1, max_length=64)
    reply_nonempty: bool
    loop_converged: bool

    @field_validator("terminal_status", mode="before")
    @classmethod
    def normalize_terminal_status(cls, value: object) -> TaskStatus | str:
        if not isinstance(value, str):
            raise ValueError("terminal status must be text")
        try:
            return TaskStatus(value)
        except ValueError:
            # Preserve malformed observations as bounded text so the
            # evaluator boundary can report a safe ERROR rather than allowing
            # the fabricated value to match an assertion.
            return value

    @model_validator(mode="after")
    def validate_safe_payload(self) -> Self:
        if self.lifecycle_status != "SUCCEEDED":
            raise ValueError("evaluation observation requires a successful run")
        if len(self.model_dump_json().encode("utf-8")) > 128 * 1_024:
            raise ValueError("evaluation observation is too large")
        return self

    @property
    def canonical_terminal_status(self) -> TaskStatus:
        """Return the canonical task status or fail for corrupt observations."""

        if isinstance(self.terminal_status, TaskStatus):
            return self.terminal_status
        return TaskStatus(self.terminal_status)


class EvalAssertion(EvalModelMixin):
    """Data-driven assertion dispatched by the evaluator registry."""

    assertion_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$",
    )
    type: str = Field(min_length=1, max_length=128)
    expected: JsonValue | None = None
    blocking: bool = True
    turn_index: int | None = Field(default=None, ge=0, strict=True)

    @field_validator("type")
    @classmethod
    def reject_blank_type(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("evaluator type must not be blank")
        return value

    @field_validator("expected")
    @classmethod
    def validate_expected(cls, value: JsonValue | None) -> JsonValue | None:
        if value is not None:
            _finite_json(value)
        return value


class EvalCase(EvalModelMixin):
    """A versioned, backend-owned Golden Case input and assertion set."""

    case_id: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$",
    )
    title: str = Field(min_length=1, max_length=MAX_CASE_TITLE_LENGTH)
    turns: list[EvalTurn] = Field(min_length=1, max_length=32)
    source_context: FiniteJsonObject = Field(default_factory=dict)
    assertions: list[EvalAssertion] = Field(min_length=1, max_length=128)
    notes: str | None = Field(default=None, max_length=MAX_CASE_NOTES_LENGTH)
    known_gap: str | None = Field(default=None, max_length=256)

    @field_validator("title")
    @classmethod
    def reject_blank_title(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("eval case title must not be blank")
        return value

    @model_validator(mode="after")
    def validate_bounded_content(self) -> Self:
        _finite_json(self.source_context)
        encoded = self.model_dump_json().encode("utf-8")
        if len(encoded) > 128 * 1_024:
            raise ValueError("eval case is too large")
        return self


class EvalSuite(EvalModelMixin):
    """A stable suite identity plus typed cases."""

    schema_version: int = Field(strict=True)
    suite_id: str = Field(min_length=1, max_length=128)
    suite_version: str = Field(min_length=1, max_length=64)
    description: str = Field(min_length=1, max_length=MAX_SUITE_DESCRIPTION_LENGTH)
    cases: list[EvalCase] = Field(min_length=1, max_length=256)

    @field_validator("suite_id", "suite_version", "description")
    @classmethod
    def reject_blank_identity_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("eval suite identity text must not be blank")
        return value

    @model_validator(mode="after")
    def validate_bounded_content(self) -> Self:
        if self.schema_version != 1:
            raise ValueError("unsupported eval suite schema version")
        case_ids = [case.case_id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("eval suite contains duplicate case IDs")
        for case in self.cases:
            assertion_ids = [item.assertion_id for item in case.assertions]
            if len(assertion_ids) != len(set(assertion_ids)):
                raise ValueError(
                    f"eval case {case.case_id} contains duplicate assertion IDs"
                )
        encoded = self.model_dump_json().encode("utf-8")
        if len(encoded) > 512 * 1_024:
            raise ValueError("eval suite is too large")
        return self


class EvalAssertionResult(EvalModelMixin):
    """Safe, bounded output of one deterministic evaluator."""

    assertion_id: str = Field(min_length=1, max_length=128)
    type: str = Field(min_length=1, max_length=128)
    blocking: bool
    status: EvalAssertionStatus
    expected_safe: JsonValue | None = None
    actual_safe: JsonValue | None = None
    message: str = Field(min_length=1, max_length=MAX_ASSERTION_MESSAGE_LENGTH)

    @field_validator("expected_safe", "actual_safe")
    @classmethod
    def validate_safe_value(cls, value: JsonValue | None) -> JsonValue | None:
        if value is not None:
            _finite_json(value)
        return value


class EvalCaseRun(EvalModelMixin):
    """Formal relation between an eval turn and a real AgentRun."""

    eval_job_id: str = Field(min_length=1, max_length=128)
    case_id: str = Field(min_length=1, max_length=64)
    turn_index: int = Field(ge=0, strict=True)
    run_id: str = Field(min_length=1, max_length=128)


class EvalCaseResult(EvalModelMixin):
    """Quality result for one case, independent from job lifecycle."""

    eval_job_id: str = Field(min_length=1, max_length=128)
    case_id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=MAX_CASE_TITLE_LENGTH)
    status: EvalCaseStatus
    known_gap: str | None = Field(default=None, max_length=256)
    run_ids: list[str] = Field(default_factory=list, max_length=32)
    assertions: list[EvalAssertionResult] = Field(default_factory=list, max_length=128)
    started_at: datetime
    completed_at: datetime | None = None
    duration_ms: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    error_code: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def validate_timing(self) -> Self:
        if self.started_at.tzinfo is None:
            raise ValueError("eval case started_at must be timezone-aware")
        if self.completed_at is not None and self.completed_at.tzinfo is None:
            raise ValueError("eval case completed_at must be timezone-aware")
        if self.completed_at is None and self.duration_ms is not None:
            raise ValueError("unfinished eval case cannot have duration")
        if self.status is EvalCaseStatus.ERROR and not self.error_code:
            raise ValueError("ERROR eval case requires an error code")
        if self.status is not EvalCaseStatus.ERROR and self.error_code is not None:
            raise ValueError("non-error eval case cannot have an error code")
        if len(self.run_ids) != len(set(self.run_ids)):
            raise ValueError("eval case run IDs must be unique")
        assertion_ids = [item.assertion_id for item in self.assertions]
        if len(assertion_ids) != len(set(assertion_ids)):
            raise ValueError("eval case assertion IDs must be unique")
        return self


class EvalJobSummary(EvalModelMixin):
    """Bounded list projection for eval-job discovery."""

    eval_job_id: str = Field(min_length=1, max_length=128)
    suite_id: str = Field(min_length=1, max_length=128)
    suite_version: str = Field(min_length=1, max_length=64)
    lifecycle_status: EvalJobLifecycleStatus
    case_count: int = Field(ge=0, strict=True)
    passed_count: int = Field(ge=0, strict=True)
    failed_count: int = Field(ge=0, strict=True)
    error_count: int = Field(ge=0, strict=True)
    started_at: datetime
    completed_at: datetime | None = None
    duration_ms: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    app_version: str = Field(min_length=1, max_length=256)
    build_sha: str | None = Field(default=None, max_length=256)
    runtime_identity: str = Field(min_length=1, max_length=256)
    error_code: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        if self.started_at.tzinfo is None:
            raise ValueError("eval job started_at must be timezone-aware")
        if self.completed_at is not None and self.completed_at.tzinfo is None:
            raise ValueError("eval job completed_at must be timezone-aware")
        if self.lifecycle_status is EvalJobLifecycleStatus.STARTED:
            if (
                self.completed_at is not None
                or self.duration_ms is not None
                or self.error_code is not None
            ):
                raise ValueError("STARTED eval job cannot be complete")
            if any((self.passed_count, self.failed_count, self.error_count)):
                raise ValueError("STARTED eval job cannot contain case counts")
        elif self.completed_at is None or self.duration_ms is None:
            raise ValueError("terminal eval job requires completion timing")
        if self.lifecycle_status is EvalJobLifecycleStatus.COMPLETED:
            if self.error_code is not None:
                raise ValueError("COMPLETED eval job cannot contain an error")
            if (
                self.passed_count + self.failed_count + self.error_count
                != self.case_count
            ):
                raise ValueError("eval job counts do not add up")
        if self.lifecycle_status is EvalJobLifecycleStatus.FAILED:
            if not self.error_code:
                raise ValueError("FAILED eval job requires an error code")
            if any((self.passed_count, self.failed_count, self.error_count)):
                raise ValueError("FAILED eval job cannot contain case counts")
        return self


class EvalJob(EvalJobSummary):
    """Complete eval job detail returned by the API and repository."""

    case_results: list[EvalCaseResult] = Field(default_factory=list, max_length=256)
    case_runs: list[EvalCaseRun] = Field(default_factory=list, max_length=512)

    @model_validator(mode="after")
    def validate_case_relations(self) -> Self:
        if self.lifecycle_status is not EvalJobLifecycleStatus.COMPLETED:
            if self.case_results or self.case_runs:
                raise ValueError("non-completed eval job cannot contain case results")
            return self
        if self.lifecycle_status is EvalJobLifecycleStatus.COMPLETED:
            if len(self.case_results) != self.case_count:
                raise ValueError("completed eval job has incomplete case results")
            case_ids = [result.case_id for result in self.case_results]
            if len(case_ids) != len(set(case_ids)):
                raise ValueError("completed eval job has duplicate case results")
            if any(
                result.eval_job_id != self.eval_job_id for result in self.case_results
            ):
                raise ValueError("case result references a different eval job")
            if any(
                relation.eval_job_id != self.eval_job_id for relation in self.case_runs
            ):
                raise ValueError("case run references a different eval job")
            result_run_ids = {
                (result.case_id, turn_index, run_id)
                for result in self.case_results
                for turn_index, run_id in enumerate(result.run_ids)
            }
            relation_run_ids = {
                (relation.case_id, relation.turn_index, relation.run_id)
                for relation in self.case_runs
            }
            if relation_run_ids != result_run_ids:
                raise ValueError("eval case run links do not match case results")
        return self


__all__ = [
    "EvalAssertion",
    "EvalAssertionResult",
    "EvalAssertionStatus",
    "EvalCase",
    "EvalCaseResult",
    "EvalCaseRun",
    "EvalCaseStatus",
    "EvalJob",
    "EvalJobLifecycleStatus",
    "EvalJobSummary",
    "EvalSuite",
    "EvalTurn",
]
