from __future__ import annotations

from datetime import UTC, datetime

import pytest

from opsmind.evals import (
    CaseEvaluationContext,
    EvalAssertion,
    EvalAssertionStatus,
    EvaluationObservation,
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
                    "abnormal": False,
                    "missing_permissions": ["EQUIPMENT_LEDGER_VIEW"],
                },
                metadata={},
                timestamp=datetime.now(UTC),
            )
        ],
        handoff=HandoffState(required=action is AgentAction.TRANSFER_HUMAN),
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
