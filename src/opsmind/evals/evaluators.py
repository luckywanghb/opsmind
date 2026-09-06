"""Generic deterministic evaluators for safe Agent execution observations."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from opsmind.evals.models import (
    EvalAssertion,
    EvalAssertionResult,
    EvalAssertionStatus,
    EvaluationObservation,
)
from opsmind.state import (
    AgentAction,
    PrimaryIntent,
    RequestType,
    RiskSignal,
    TaskStatus,
)

EvaluatorFunction = Callable[
    [EvalAssertion, "CaseEvaluationContext"], EvalAssertionResult
]


@dataclass(frozen=True, slots=True)
class CaseEvaluationContext:
    """Transient aggregate of per-turn safe observations for one case."""

    observations: tuple[EvaluationObservation, ...]

    @property
    def run_ids(self) -> tuple[str, ...]:
        return tuple(item.run_id for item in self.observations)

    @property
    def request_ids(self) -> tuple[str, ...]:
        return tuple(item.request_id for item in self.observations)

    @property
    def thread_ids(self) -> tuple[str, ...]:
        return tuple(item.thread_id for item in self.observations)


def _safe(value: Any, *, depth: int = 0) -> Any:
    """Keep evaluator output bounded and limited to scalar-ish safe values."""

    if depth > 3:
        return "<bounded>"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value if len(value) <= 256 else f"{value[:255]}…"
    if isinstance(value, Mapping):
        return {
            str(key)[:128]: _safe(item, depth=depth + 1)
            for key, item in list(value.items())[:32]
        }
    if isinstance(value, (list, tuple, set)):
        return [_safe(item, depth=depth + 1) for item in list(value)[:32]]
    return str(value)[:256]


def _json_values_equal(actual: object, expected: object) -> bool:
    """Compare JSON values without Python's bool/int equality trap."""

    if type(actual) is not type(expected):
        return False
    if isinstance(actual, dict):
        if not isinstance(expected, dict) or actual.keys() != expected.keys():
            return False
        return all(
            _json_values_equal(actual[key], expected[key]) for key in actual
        )
    if isinstance(actual, list):
        if not isinstance(expected, list) or len(actual) != len(expected):
            return False
        return all(
            _json_values_equal(actual_item, expected_item)
            for actual_item, expected_item in zip(actual, expected, strict=True)
        )
    return actual == expected


def _error(assertion: EvalAssertion, message: str) -> EvalAssertionResult:
    return EvalAssertionResult(
        assertion_id=assertion.assertion_id,
        type=assertion.type,
        blocking=assertion.blocking,
        status=EvalAssertionStatus.ERROR,
        expected_safe=_safe(assertion.expected),
        actual_safe=None,
        message=message,
    )


def _result(
    assertion: EvalAssertion,
    passed: bool,
    *,
    actual: Any,
    message: str,
) -> EvalAssertionResult:
    return EvalAssertionResult(
        assertion_id=assertion.assertion_id,
        type=assertion.type,
        blocking=assertion.blocking,
        status=EvalAssertionStatus.PASS if passed else EvalAssertionStatus.FAIL,
        expected_safe=_safe(assertion.expected),
        actual_safe=_safe(actual),
        message=message,
    )


def _targets(
    assertion: EvalAssertion,
    context: CaseEvaluationContext,
) -> tuple[EvaluationObservation, ...]:
    if assertion.turn_index is None:
        return context.observations[-1:] if context.observations else ()
    if assertion.turn_index >= len(context.observations):
        return ()
    return (context.observations[assertion.turn_index],)


def _expected_list(assertion: EvalAssertion) -> tuple[Any, ...] | None:
    expected = assertion.expected
    if isinstance(expected, list):
        return tuple(expected)
    if expected is None:
        return None
    return (expected,)


def _enum_in(
    assertion: EvalAssertion,
    context: CaseEvaluationContext,
    values: Iterable[str | None],
) -> EvalAssertionResult:
    expected = _expected_list(assertion)
    targets = _targets(assertion, context)
    actual_values = list(values)
    if (
        expected is None
        or not targets
        or not all(isinstance(item, str) for item in expected)
        or not all(isinstance(item, str) for item in actual_values)
    ):
        return _error(assertion, "assertion expectation or observation is invalid")
    actual = [value for value in actual_values if isinstance(value, str)]
    passed = all(value in expected for value in actual) and bool(actual)
    return _result(
        assertion,
        passed,
        actual=actual[-1] if len(actual) == 1 else actual,
        message=(
            "value is within the expected set"
            if passed
            else "value is outside the expected set"
        ),
    )


def _enum_value(value: StrEnum | None) -> str | None:
    return value.value if value is not None else None


def _run_lifecycle_succeeded(
    assertion: EvalAssertion,
    context: CaseEvaluationContext,
) -> EvalAssertionResult:
    expected = assertion.expected
    targets = _targets(assertion, context)
    if not isinstance(expected, bool) or not targets:
        return _error(
            assertion,
            "expected boolean and at least one observation are required",
        )
    actual = all(item.lifecycle_status == "SUCCEEDED" for item in targets)
    return _result(
        assertion,
        actual is expected,
        actual=actual,
        message="run lifecycle checked",
    )


def _intent_in(
    assertion: EvalAssertion, context: CaseEvaluationContext
) -> EvalAssertionResult:
    return _enum_in(
        assertion,
        context,
        (
            _enum_value(item.understanding.primary_intent)
            for item in _targets(assertion, context)
        ),
    )


def _request_type_in(
    assertion: EvalAssertion,
    context: CaseEvaluationContext,
) -> EvalAssertionResult:
    return _enum_in(
        assertion,
        context,
        (
            _enum_value(item.understanding.request_type)
            for item in _targets(assertion, context)
        ),
    )


def _risk_signal_in(
    assertion: EvalAssertion,
    context: CaseEvaluationContext,
) -> EvalAssertionResult:
    return _enum_in(
        assertion,
        context,
        (
            _enum_value(item.understanding.risk_signal)
            for item in _targets(assertion, context)
        ),
    )


def _final_action_in(
    assertion: EvalAssertion,
    context: CaseEvaluationContext,
) -> EvalAssertionResult:
    return _enum_in(
        assertion,
        context,
        (
            _enum_value(item.final_decision.action)
            for item in _targets(assertion, context)
        ),
    )


def _terminal_status_in(
    assertion: EvalAssertion,
    context: CaseEvaluationContext,
) -> EvalAssertionResult:
    expected = assertion.expected
    targets = _targets(assertion, context)
    if (
        not isinstance(expected, list)
        or not expected
        or not all(isinstance(item, str) for item in expected)
        or not targets
    ):
        return _error(assertion, "task status expectation is required")
    expected_strings = [item for item in expected if isinstance(item, str)]
    try:
        expected_statuses = [TaskStatus(item).value for item in expected_strings]
        actual = [item.canonical_terminal_status.value for item in targets]
    except (TypeError, ValueError):
        return _error(assertion, "observation terminal status is invalid")
    passed = all(value in expected_statuses for value in actual) and bool(actual)
    return _result(
        assertion,
        passed,
        actual=actual[-1] if len(actual) == 1 else actual,
        message=(
            "value is within the expected set"
            if passed
            else "value is outside the expected set"
        ),
    )


def _required_tool_used(
    assertion: EvalAssertion,
    context: CaseEvaluationContext,
) -> EvalAssertionResult:
    expected = _expected_list(assertion)
    if (
        expected is None
        or not expected
        or not all(isinstance(item, str) for item in expected)
    ):
        return _error(assertion, "expected tool name is required")
    targets = (
        _targets(assertion, context)
        if assertion.turn_index is not None
        else context.observations
    )
    if not targets:
        return _error(assertion, "observation target is unavailable")
    actual = [call.tool_name for item in targets for call in item.tool_calls]
    passed = all(tool in actual for tool in expected)
    return _result(
        assertion,
        passed,
        actual=actual,
        message="required tool usage checked",
    )


def _forbidden_tool_not_used(
    assertion: EvalAssertion,
    context: CaseEvaluationContext,
) -> EvalAssertionResult:
    expected = _expected_list(assertion)
    if (
        expected is None
        or not expected
        or not all(isinstance(item, str) for item in expected)
    ):
        return _error(assertion, "forbidden tool name is required")
    targets = (
        _targets(assertion, context)
        if assertion.turn_index is not None
        else context.observations
    )
    if not targets:
        return _error(assertion, "observation target is unavailable")
    actual = [call.tool_name for item in targets for call in item.tool_calls]
    forbidden = [tool for tool in actual if tool in expected]
    return _result(
        assertion,
        not forbidden,
        actual=forbidden,
        message="forbidden tool usage checked",
    )


def _tool_argument_equals(
    assertion: EvalAssertion,
    context: CaseEvaluationContext,
) -> EvalAssertionResult:
    expected = assertion.expected
    if not isinstance(expected, dict):
        return _error(assertion, "tool argument expectation must be an object")
    tool_value = expected.get("tool", expected.get("tool_name"))
    field_value = expected.get("field")
    value = expected.get("value")
    if (
        not isinstance(tool_value, str)
        or not isinstance(field_value, str)
        or "value" not in expected
    ):
        return _error(assertion, "tool, field, and value are required")
    tool = tool_value
    field = field_value
    targets = (
        _targets(assertion, context)
        if assertion.turn_index is not None
        else context.observations
    )
    if not targets:
        return _error(assertion, "observation target is unavailable")
    actual_values = [
        call.arguments.get(field)
        for item in targets
        for call in item.tool_calls
        if call.tool_name == tool and field in call.arguments
    ]
    passed = any(_json_values_equal(actual, value) for actual in actual_values)
    return _result(
        assertion,
        passed,
        actual=actual_values,
        message="tool argument checked",
    )


def _tool_call_count_lte(
    assertion: EvalAssertion,
    context: CaseEvaluationContext,
) -> EvalAssertionResult:
    expected = assertion.expected
    if not isinstance(expected, int) or isinstance(expected, bool) or expected < 0:
        return _error(assertion, "non-negative integer limit is required")
    targets = (
        _targets(assertion, context)
        if assertion.turn_index is not None
        else context.observations
    )
    if not targets:
        return _error(assertion, "observation target is unavailable")
    actual = sum(len(item.tool_calls) for item in targets)
    return _result(
        assertion,
        actual <= expected,
        actual=actual,
        message="tool call count checked",
    )


def _evidence_count_gte(
    assertion: EvalAssertion,
    context: CaseEvaluationContext,
) -> EvalAssertionResult:
    expected = assertion.expected
    if not isinstance(expected, int) or isinstance(expected, bool) or expected < 0:
        return _error(assertion, "non-negative integer threshold is required")
    targets = _targets(assertion, context)
    if not targets:
        return _error(assertion, "observation target is unavailable")
    actual = sum(len(item.evidence) for item in targets)
    return _result(
        assertion,
        actual >= expected,
        actual=actual,
        message="evidence count checked",
    )


def _evidence_source_present(
    assertion: EvalAssertion,
    context: CaseEvaluationContext,
) -> EvalAssertionResult:
    expected = _expected_list(assertion)
    if (
        expected is None
        or not expected
        or not all(isinstance(item, str) for item in expected)
    ):
        return _error(assertion, "evidence source is required")
    targets = _targets(assertion, context)
    if not targets:
        return _error(assertion, "observation target is unavailable")
    actual = [item.source for target in targets for item in target.evidence]
    return _result(
        assertion,
        all(source in actual for source in expected),
        actual=actual,
        message="evidence source checked",
    )


def _evidence_field(
    assertion: EvalAssertion,
    context: CaseEvaluationContext,
    *,
    contains: bool,
) -> EvalAssertionResult:
    expected = assertion.expected
    if not isinstance(expected, dict):
        return _error(assertion, "evidence field expectation must be an object")
    field = expected.get("field")
    expected_value = expected.get("value")
    source = expected.get("source")
    if not isinstance(field, str) or "value" not in expected:
        return _error(assertion, "field and value are required")
    if source is not None and not isinstance(source, str):
        return _error(assertion, "source must be a string")
    targets = _targets(assertion, context)
    if not targets:
        return _error(assertion, "observation target is unavailable")
    actual_values = [
        item.key_fields.get(field)
        for target in targets
        for item in target.evidence
        if source is None or item.source == source
        if field in item.key_fields
    ]
    if contains:
        passed = any(
            (
                isinstance(actual, list)
                and any(_json_values_equal(item, expected_value) for item in actual)
            )
            or (
                isinstance(actual, str)
                and isinstance(expected_value, str)
                and expected_value in actual
            )
            for actual in actual_values
        )
    else:
        passed = any(
            _json_values_equal(actual, expected_value) for actual in actual_values
        )
    return _result(
        assertion,
        passed,
        actual=actual_values,
        message="evidence field checked",
    )


def _reply_nonempty(
    assertion: EvalAssertion,
    context: CaseEvaluationContext,
) -> EvalAssertionResult:
    expected = assertion.expected
    targets = _targets(assertion, context)
    if not isinstance(expected, bool) or not targets:
        return _error(assertion, "expected boolean and observation are required")
    actual = all(item.reply_nonempty for item in targets)
    return _result(
        assertion,
        actual is expected,
        actual=actual,
        message="reply presence checked",
    )


def _handoff_required(
    assertion: EvalAssertion,
    context: CaseEvaluationContext,
) -> EvalAssertionResult:
    expected = assertion.expected
    targets = _targets(assertion, context)
    if not isinstance(expected, bool) or not targets:
        return _error(assertion, "expected boolean and observation are required")
    actual = all(item.handoff.required for item in targets)
    return _result(
        assertion,
        actual is expected,
        actual=actual,
        message="handoff requirement checked",
    )


def _same_thread_across_turns(
    assertion: EvalAssertion,
    context: CaseEvaluationContext,
) -> EvalAssertionResult:
    expected = assertion.expected
    if not isinstance(expected, bool) or len(context.observations) < 2:
        return _error(assertion, "two or more observations and a boolean are required")
    same_thread = len(set(context.thread_ids)) == 1
    distinct_requests = len(set(context.request_ids)) == len(context.request_ids)
    distinct_runs = len(set(context.run_ids)) == len(context.run_ids)
    actual = same_thread and distinct_requests and distinct_runs
    return _result(
        assertion,
        actual is expected,
        actual={
            "same_thread": same_thread,
            "distinct_request_ids": distinct_requests,
            "distinct_run_ids": distinct_runs,
        },
        message="multi-turn identity continuity checked",
    )


def _loop_converged(
    assertion: EvalAssertion,
    context: CaseEvaluationContext,
) -> EvalAssertionResult:
    expected = assertion.expected
    targets = _targets(assertion, context)
    if not isinstance(expected, bool) or not targets:
        return _error(assertion, "expected boolean and observation are required")
    actual = all(item.loop_converged for item in targets)
    return _result(
        assertion,
        actual is expected,
        actual=actual,
        message="loop convergence checked",
    )


class EvaluatorRegistry:
    """Registry of generic, data-driven deterministic evaluator functions."""

    _default: dict[str, EvaluatorFunction] = {
        "run_lifecycle_succeeded": _run_lifecycle_succeeded,
        "intent_in": _intent_in,
        "request_type_in": _request_type_in,
        "risk_signal_in": _risk_signal_in,
        "final_action_in": _final_action_in,
        "terminal_status_in": _terminal_status_in,
        "required_tool_used": _required_tool_used,
        "forbidden_tool_not_used": _forbidden_tool_not_used,
        "tool_argument_equals": _tool_argument_equals,
        "tool_call_count_lte": _tool_call_count_lte,
        "evidence_count_gte": _evidence_count_gte,
        "evidence_source_present": _evidence_source_present,
        "evidence_field_equals": lambda assertion, context: _evidence_field(
            assertion, context, contains=False
        ),
        "evidence_field_contains": lambda assertion, context: _evidence_field(
            assertion, context, contains=True
        ),
        "reply_nonempty": _reply_nonempty,
        "handoff_required": _handoff_required,
        "same_thread_across_turns": _same_thread_across_turns,
        "loop_converged": _loop_converged,
    }

    _enum_expectations: dict[str, type[StrEnum]] = {
        "intent_in": PrimaryIntent,
        "request_type_in": RequestType,
        "risk_signal_in": RiskSignal,
        "final_action_in": AgentAction,
        "terminal_status_in": TaskStatus,
    }

    def __init__(
        self,
        evaluators: Mapping[str, EvaluatorFunction] | None = None,
    ) -> None:
        self._evaluators = dict(self._default)
        if evaluators:
            self._evaluators.update(evaluators)

    @property
    def types(self) -> tuple[str, ...]:
        return tuple(self._evaluators)

    def supports(self, evaluator_type: str) -> bool:
        return evaluator_type in self._evaluators

    def validate_assertion(
        self,
        assertion: EvalAssertion,
        *,
        turn_count: int,
    ) -> None:
        """Validate one assertion's evaluator-specific input contract."""

        if not self.supports(assertion.type):
            raise ValueError("unknown evaluator type")
        if assertion.turn_index is not None and assertion.turn_index >= turn_count:
            raise ValueError("assertion turn index is outside the case turns")

        expected = assertion.expected
        if assertion.type in self._enum_expectations:
            enum_type = self._enum_expectations[assertion.type]
            expected_strings = [
                item for item in expected if isinstance(item, str)
            ] if isinstance(expected, list) else []
            allowed_values = {member.value for member in enum_type}
            if (
                not isinstance(expected, list)
                or not expected
                or len(expected_strings) != len(expected)
                or any(item not in allowed_values for item in expected_strings)
            ):
                raise ValueError("evaluator expects a non-empty allowed enum list")
            return

        if assertion.type in {
            "required_tool_used",
            "forbidden_tool_not_used",
            "evidence_source_present",
        }:
            if (
                not isinstance(expected, list)
                or not expected
                or not all(isinstance(item, str) and item.strip() for item in expected)
            ):
                raise ValueError("evaluator expects a non-empty string list")
            return

        if assertion.type in {
            "run_lifecycle_succeeded",
            "reply_nonempty",
            "handoff_required",
            "same_thread_across_turns",
            "loop_converged",
        }:
            if not isinstance(expected, bool):
                raise ValueError("evaluator expects a boolean")
            if assertion.type == "same_thread_across_turns" and turn_count < 2:
                raise ValueError("multi-turn evaluator requires two turns")
            return

        if assertion.type in {"tool_call_count_lte", "evidence_count_gte"}:
            if (
                not isinstance(expected, int)
                or isinstance(expected, bool)
                or expected < 0
            ):
                raise ValueError("evaluator expects a non-negative integer")
            return

        if assertion.type == "tool_argument_equals":
            if not isinstance(expected, dict):
                raise ValueError("tool argument expectation must be an object")
            allowed = {"tool", "tool_name", "field", "value"}
            tool_keys = {key for key in ("tool", "tool_name") if key in expected}
            if (
                set(expected) - allowed
                or len(tool_keys) != 1
                or "field" not in expected
                or "value" not in expected
            ):
                raise ValueError("tool, field, and value are required")
            tool_key = next(iter(tool_keys))
            tool_value = expected[tool_key]
            field_value = expected["field"]
            if not isinstance(tool_value, str) or not isinstance(field_value, str):
                raise ValueError("tool, field, and value are required")
            if not tool_value.strip() or not field_value.strip():
                raise ValueError("tool, field, and value are required")
            return

        if assertion.type in {"evidence_field_equals", "evidence_field_contains"}:
            if not isinstance(expected, dict):
                raise ValueError("evidence field expectation must be an object")
            if (
                set(expected) - {"source", "field", "value"}
                or "field" not in expected
                or "value" not in expected
                or not isinstance(expected["field"], str)
                or not expected["field"].strip()
                or (
                    "source" in expected
                    and (
                        not isinstance(expected["source"], str)
                        or not expected["source"].strip()
                    )
                )
            ):
                raise ValueError("field and value are required")
            return

        # Custom evaluator functions own their expectation schema.  The
        # loader still enforces registration and turn-index integrity.

    def evaluate(
        self,
        assertion: EvalAssertion,
        context: CaseEvaluationContext,
    ) -> EvalAssertionResult:
        evaluator = self._evaluators.get(assertion.type)
        if evaluator is None:
            return _error(assertion, "unknown evaluator type")
        try:
            for observation in context.observations:
                _ = observation.canonical_terminal_status
            result = evaluator(assertion, context)
        except Exception:
            # Evaluator failures are safe assertion errors.  Never stringify
            # malformed observations or exception details into the result.
            return _error(assertion, "evaluator could not inspect observation")
        return EvalAssertionResult.model_validate(result)


__all__ = ["CaseEvaluationContext", "EvaluatorRegistry", "EvaluatorFunction"]
