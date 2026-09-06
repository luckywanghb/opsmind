from __future__ import annotations

from datetime import UTC, datetime

import pytest

from opsmind.evals import (
    CaseEvaluationContext,
    EvalAssertion,
    EvalAssertionResult,
    EvalAssertionStatus,
    EvaluationObservation,
    EvaluationObservationErrorCode,
    EvaluatorRegistry,
    ToolCallObservation,
)
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


def _observation(
    *,
    run_id: str = "run-1",
    request_id: str = "request-1",
    thread_id: str = "thread-1",
    request_type: RequestType = RequestType.DIAGNOSE,
    action: AgentAction = AgentAction.SEARCH,
    observation_error_code: EvaluationObservationErrorCode | None = None,
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
            rationale="typed observation",
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
                summary="typed result",
                key_fields={
                    "status": "APPROVING",
                    "current_handler": "U10108",
                    "waiting_hours": 4.0,
                    "abnormal": False,
                    "missing_permissions": ["EQUIPMENT_LEDGER_VIEW"],
                },
                metadata={},
                timestamp=datetime.now(UTC),
            )
        ],
        handoff=HandoffState(required=action is AgentAction.TRANSFER_HUMAN),
        observation_error_code=observation_error_code,
        terminal_status="RESOLVED",
        reply_nonempty=True,
        loop_converged=True,
    )


def _evaluate(
    assertion_type: str,
    expected: object,
    *,
    context: CaseEvaluationContext | None = None,
    **kwargs: object,
) -> EvalAssertionStatus:
    assertion = EvalAssertion(
        assertion_id="assertion",
        type=assertion_type,
        expected=expected,
        **kwargs,
    )
    return (
        EvaluatorRegistry()
        .evaluate(
            assertion,
            context or CaseEvaluationContext((_observation(),)),
        )
        .status
    )


@pytest.mark.parametrize(
    ("assertion_type", "expected"),
    [
        ("run_lifecycle_succeeded", True),
        ("intent_in", ["WORKFLOW_ISSUE"]),
        ("request_type_in", ["DIAGNOSE"]),
        ("risk_signal_in", ["NONE"]),
        ("final_action_in", ["SEARCH"]),
        ("terminal_status_in", ["RESOLVED"]),
        ("required_tool_used", ["work_order_query"]),
        ("forbidden_tool_not_used", ["permission_mutation"]),
        (
            "tool_argument_equals",
            {
                "tool": "work_order_query",
                "field": "work_order_id",
                "value": "WO20260001",
            },
        ),
        ("tool_call_count_lte", 1),
        ("evidence_count_gte", 1),
        ("evidence_source_present", ["work_order_query"]),
        (
            "evidence_field_equals",
            {"source": "work_order_query", "field": "status", "value": "APPROVING"},
        ),
        (
            "evidence_field_contains",
            {
                "source": "work_order_query",
                "field": "missing_permissions",
                "value": "EQUIPMENT_LEDGER_VIEW",
            },
        ),
        ("reply_nonempty", True),
        ("handoff_required", False),
        ("loop_converged", True),
    ],
)
def test_each_deterministic_evaluator_has_a_pass_path(
    assertion_type: str,
    expected: object,
) -> None:
    assert _evaluate(assertion_type, expected) is EvalAssertionStatus.PASS


_DEFAULT_EVALUATOR_MATRIX = [
    ("run_lifecycle_succeeded", True, False, False),
    ("intent_in", ["WORKFLOW_ISSUE"], ["ACCESS_ISSUE"], False),
    ("request_type_in", ["DIAGNOSE"], ["HOW_TO"], False),
    ("risk_signal_in", ["NONE"], ["BROAD_OUTAGE"], False),
    ("final_action_in", ["SEARCH"], ["REPLY"], False),
    ("terminal_status_in", ["RESOLVED"], ["WAITING_USER"], False),
    ("required_tool_used", ["work_order_query"], ["permission_query"], False),
    (
        "forbidden_tool_not_used",
        ["permission_mutation"],
        ["work_order_query"],
        False,
    ),
    (
        "tool_argument_equals",
        {
            "tool": "work_order_query",
            "field": "work_order_id",
            "value": "WO20260001",
        },
        {
            "tool": "work_order_query",
            "field": "work_order_id",
            "value": "WO99999999",
        },
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
]


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


@pytest.mark.parametrize(
    ("assertion_type", "passing_expected", "failing_expected", "multi_turn"),
    _DEFAULT_EVALUATOR_MATRIX,
)
def test_every_default_evaluator_has_pass_fail_and_invalid_observation_paths(
    assertion_type: str,
    passing_expected: object,
    failing_expected: object,
    multi_turn: bool,
) -> None:
    registry = EvaluatorRegistry()

    def evaluate(
        expected: object,
        context: CaseEvaluationContext,
    ) -> EvalAssertionStatus:
        return registry.evaluate(
            EvalAssertion(
                assertion_id=f"{assertion_type}-matrix",
                type=assertion_type,
                expected=expected,
            ),
            context,
        ).status

    assert (
        evaluate(
            passing_expected,
            _matrix_context(multi_turn=multi_turn),
        )
        is EvalAssertionStatus.PASS
    )
    assert (
        evaluate(
            failing_expected,
            _matrix_context(multi_turn=multi_turn),
        )
        is EvalAssertionStatus.FAIL
    )
    assert (
        evaluate(
            passing_expected,
            _matrix_context(
                multi_turn=multi_turn,
                observation_error_code=(
                    EvaluationObservationErrorCode.TOOL_ARGUMENTS_UNAVAILABLE
                ),
            ),
        )
        is EvalAssertionStatus.ERROR
    )


def test_default_evaluator_matrix_covers_the_complete_registry() -> None:
    assert {row[0] for row in _DEFAULT_EVALUATOR_MATRIX} == set(
        EvaluatorRegistry().types
    )


def test_registered_evaluator_exception_is_a_safe_assertion_error() -> None:
    def raising_evaluator(
        assertion: EvalAssertion,
        context: CaseEvaluationContext,
    ) -> EvalAssertionResult:
        raise RuntimeError("private evaluator detail")

    result = EvaluatorRegistry({"raising": raising_evaluator}).evaluate(
        EvalAssertion(assertion_id="raising", type="raising", expected=True),
        CaseEvaluationContext((_observation(),)),
    )

    assert result.status is EvalAssertionStatus.ERROR
    assert "private evaluator detail" not in result.message


@pytest.mark.parametrize(
    ("field", "correct_value", "wrong_value"),
    [
        ("current_handler", "U10108", "U99999"),
        ("waiting_hours", 4, 5),
    ],
)
def test_c05_pm_owned_evidence_truth_rejects_wrong_values(
    field: str,
    correct_value: object,
    wrong_value: object,
) -> None:
    registry = EvaluatorRegistry()

    def evaluate(value: object) -> EvalAssertionStatus:
        return registry.evaluate(
            EvalAssertion(
                assertion_id=f"c05-{field}",
                type="evidence_field_equals",
                expected={
                    "source": "work_order_query",
                    "field": field,
                    "value": value,
                },
            ),
            CaseEvaluationContext((_observation(),)),
        ).status

    assert evaluate(correct_value) is EvalAssertionStatus.PASS
    assert evaluate(wrong_value) is EvalAssertionStatus.FAIL


def test_c06_request_type_truth_rejects_wrong_value() -> None:
    result = EvaluatorRegistry().evaluate(
        EvalAssertion(
            assertion_id="c06-request",
            type="request_type_in",
            expected=["DIAGNOSE"],
        ),
        CaseEvaluationContext(
            (_observation(request_type=RequestType.HOW_TO),)
        ),
    )

    assert result.status is EvalAssertionStatus.FAIL


def test_same_thread_assertion_checks_all_three_ids() -> None:
    context = CaseEvaluationContext(
        (
            _observation(run_id="run-1", request_id="request-1"),
            _observation(run_id="run-2", request_id="request-2"),
        )
    )
    assert (
        _evaluate("same_thread_across_turns", True, context=context)
        is EvalAssertionStatus.PASS
    )


@pytest.mark.parametrize(
    ("assertion_type", "expected"),
    [
        ("intent_in", ["ACCESS_ISSUE"]),
        ("required_tool_used", ["permission_query"]),
        ("tool_call_count_lte", 0),
        (
            "evidence_field_equals",
            {"field": "status", "value": "FAILED"},
        ),
        ("reply_nonempty", False),
    ],
)
def test_evaluators_report_quality_mismatch_as_fail(
    assertion_type: str,
    expected: object,
) -> None:
    assert _evaluate(assertion_type, expected) is EvalAssertionStatus.FAIL


@pytest.mark.parametrize(
    ("assertion_type", "expected"),
    [
        ("required_tool_used", None),
        ("tool_argument_equals", {"tool": "work_order_query"}),
        ("same_thread_across_turns", True),
    ],
)
def test_invalid_observations_or_expectations_report_error(
    assertion_type: str,
    expected: object,
) -> None:
    context = (
        CaseEvaluationContext(())
        if assertion_type == "same_thread_across_turns"
        else None
    )
    assert (
        _evaluate(assertion_type, expected, context=context)
        is EvalAssertionStatus.ERROR
    )
