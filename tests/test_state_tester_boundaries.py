"""Independent tester-owned boundaries for the finalized state contract."""

import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from opsmind import (
    AgentAction,
    ConversationState,
    EvidenceItem,
    OpsAgentState,
    ResolutionStatus,
    TaskState,
    TaskStatus,
)
from opsmind.state import (
    EVIDENCE_MAX_COLLECTION_ITEMS,
    EVIDENCE_MAX_NESTING_DEPTH,
    EVIDENCE_MAX_STRING_LENGTH,
)


@pytest.mark.parametrize("status", list(TaskStatus))
def test_every_task_status_is_typed_and_json_serializable(
    status: TaskStatus,
) -> None:
    state = OpsAgentState(task={"status": status})

    encoded = state.model_dump_json()
    assert json.loads(encoded)["task"]["status"] == status.value
    restored = OpsAgentState.model_validate_json(encoded)

    assert restored.task.status is status


@pytest.mark.parametrize("status", list(ResolutionStatus))
def test_every_resolution_status_is_typed_and_json_serializable(
    status: ResolutionStatus,
) -> None:
    state = OpsAgentState(
        conversation={"previous_resolution_status": status},
    )

    encoded = state.model_dump_json()
    assert (
        json.loads(encoded)["conversation"]["previous_resolution_status"]
        == status.value
    )
    restored = OpsAgentState.model_validate_json(encoded)

    assert restored.conversation.previous_resolution_status is status


def test_task_and_resolution_status_remain_separate_axes() -> None:
    state = OpsAgentState(
        task={"status": TaskStatus.WAITING_USER},
        conversation={
            "previous_resolution_status": ResolutionStatus.UNRESOLVED,
        },
    )

    assert type(state.task.status) is TaskStatus
    assert type(state.conversation.previous_resolution_status) is ResolutionStatus
    assert TaskState.model_fields["status"].annotation == TaskStatus | None
    assert (
        ConversationState.model_fields["previous_resolution_status"].annotation
        == ResolutionStatus | None
    )


def test_status_fields_reject_invalid_values_on_assignment() -> None:
    state = OpsAgentState(
        task={"status": TaskStatus.ACTIVE},
        conversation={"previous_resolution_status": ResolutionStatus.UNKNOWN},
    )

    with pytest.raises(ValidationError):
        state.task.status = "IN_PROGRESS"
    with pytest.raises(ValidationError):
        state.conversation.previous_resolution_status = "DONE"


@pytest.mark.parametrize("goal", [123, [], {"text": "not a string"}])
def test_decision_goal_rejects_non_text_payloads(goal: object) -> None:
    with pytest.raises(ValidationError):
        OpsAgentState.model_validate(
            {
                "decision": {
                    "action": AgentAction.SEARCH,
                    "goal": goal,
                    "rationale": "Need current evidence.",
                }
            }
        )


def test_decision_goal_is_declared_and_extra_decision_fields_are_rejected() -> None:
    state = OpsAgentState(
        decision={
            "action": AgentAction.SEARCH,
            "goal": "Confirm the current workflow node.",
            "rationale": "The current state is missing.",
        }
    )
    assert state.decision.goal == "Confirm the current workflow node."

    with pytest.raises(ValidationError):
        OpsAgentState.model_validate(
            {"decision": {"goal": "x", "unexpected": True}}
        )


def test_evidence_accepts_exact_structural_boundaries() -> None:
    nested: object = "value"
    for _ in range(EVIDENCE_MAX_NESTING_DEPTH - 1):
        nested = {"level": nested}

    item = EvidenceItem(
        source="boundary",
        summary="boundary",
        key_fields={
            "nested": nested,
            "events": list(range(EVIDENCE_MAX_COLLECTION_ITEMS)),
        },
        metadata={"excerpt": "x" * EVIDENCE_MAX_STRING_LENGTH},
        timestamp=datetime(2026, 8, 30, 9, 30, tzinfo=UTC),
    )

    assert item.key_fields["events"] == list(range(EVIDENCE_MAX_COLLECTION_ITEMS))
    assert item.metadata["excerpt"] == "x" * EVIDENCE_MAX_STRING_LENGTH
