"""Unit tests for the V0.1 OpsAgentState contract."""

import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from opsmind import (
    AgentAction,
    CapabilityMode,
    EvidenceItem,
    OpsAgentState,
    PrimaryIntent,
    RequestType,
    RiskSignal,
)


def test_minimal_state_has_all_sections_and_read_only_safety() -> None:
    state = OpsAgentState()

    assert set(OpsAgentState.model_fields) == {
        "identity",
        "conversation",
        "understanding",
        "task",
        "loop",
        "facts",
        "evidence",
        "decision",
        "tool",
        "safety",
        "handoff",
        "response",
    }
    assert state.safety.capability is CapabilityMode.READ_ONLY


def test_enums_match_the_architecture_taxonomies() -> None:
    assert {item.value for item in PrimaryIntent} == {
        "SYSTEM_OPERATION",
        "BUSINESS_RULE",
        "ACCESS_ISSUE",
        "WORKFLOW_ISSUE",
        "DATA_ISSUE",
        "OTHER",
    }
    assert {item.value for item in RequestType} == {
        "HOW_TO",
        "EXPLAIN",
        "DIAGNOSE",
        "CHECK_STATUS",
        "EXECUTE_CHANGE",
        "CONTINUE_CASE",
        "CONFIRM_RESOLVED",
        "OTHER",
    }
    assert {item.value for item in RiskSignal} == {
        "NONE",
        "PRIVILEGED_CHANGE",
        "BROAD_OUTAGE",
        "SECURITY_SUSPECTED",
        "DESTRUCTIVE_OPERATION",
    }
    assert {item.value for item in AgentAction} == {
        "ASK_USER",
        "SEARCH",
        "REPLY",
        "TRANSFER_HUMAN",
        "END_CONVERSATION",
    }
    assert {item.value for item in CapabilityMode} == {"READ_ONLY"}


def test_full_representative_state() -> None:
    observed_at = datetime(2026, 8, 30, 9, 30, tzinfo=UTC)
    state = OpsAgentState(
        identity={
            "user_id": "U10023",
            "site_id": "SITE-SH-01",
            "department": "Manufacturing IT",
            "roles": ["operator"],
            "source_context": {"channel": "support_portal"},
        },
        conversation={
            "thread_id": "thread-001",
            "original_query": "The plant system returns HTTP 500.",
            "current_query": "Is the whole site affected?",
            "summary": "The user cannot open the manufacturing system.",
            "previous_resolution_status": "UNRESOLVED",
        },
        understanding={
            "primary_intent": PrimaryIntent.SYSTEM_OPERATION,
            "request_type": RequestType.DIAGNOSE,
            "symptom": "HTTP 500",
            "entities": {"system": "MES"},
            "risk_signal": RiskSignal.BROAD_OUTAGE,
            "uncertainty": "Impact scope is not yet confirmed.",
        },
        task={
            "objective": "Determine the outage scope.",
            "status": "IN_PROGRESS",
            "constraints": ["read-only"],
        },
        loop={
            "round_count": 1,
            "tool_call_count": 1,
            "retry_count": 0,
            "max_rounds": 6,
            "max_tool_calls": 8,
            "max_retries": 2,
            "tool_timeout_seconds": 20.0,
        },
        facts={
            "confirmed": ["The user received HTTP 500."],
            "unresolved_questions": ["Are other users affected?"],
        },
        evidence={
            "items": [
                {
                    "source": "synthetic_log_search",
                    "summary": "Five recent HTTP 500 events were found.",
                    "key_fields": {"event_count": 5, "service": "MES"},
                    "metadata": {"query_id": "query-42"},
                    "artifact_ref": "artifact://logs/query-42",
                    "timestamp": observed_at,
                }
            ]
        },
        decision={
            "action": AgentAction.ASK_USER,
            "rationale": "The current impact scope is unresolved.",
        },
        tool={
            "selected_tool": "synthetic_incident_search",
            "arguments": {"site_id": "SITE-SH-01"},
            "expected_resolution": "Establish whether an incident is active.",
        },
        safety={"capability": CapabilityMode.READ_ONLY},
        handoff={"required": False},
        response={
            "message": "Are colleagues at the same site also affected?",
            "is_final": False,
        },
    )

    assert state.understanding.primary_intent is PrimaryIntent.SYSTEM_OPERATION
    assert state.decision.action is AgentAction.ASK_USER
    assert state.evidence.items[0].timestamp == observed_at


@pytest.mark.parametrize(
    ("payload", "location"),
    [
        ({"understanding": {"primary_intent": "NOT_AN_INTENT"}}, "primary_intent"),
        ({"unexpected": True}, "unexpected"),
        ({"facts": {"raw_result": "large payload"}}, "raw_result"),
        (
            {
                "evidence": {
                    "items": [
                        {
                            "source": "log_search",
                            "summary": "A compact summary.",
                            "timestamp": "2026-08-30T09:30:00Z",
                            "raw_result": ["unbounded", "tool", "output"],
                        }
                    ]
                }
            },
            "raw_result",
        ),
    ],
)
def test_invalid_enum_and_unknown_fields_are_rejected(
    payload: dict[str, object], location: str
) -> None:
    with pytest.raises(ValidationError) as error:
        OpsAgentState.model_validate(payload)

    assert location in str(error.value)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("round_count", -1),
        ("tool_call_count", -1),
        ("retry_count", -1),
        ("max_rounds", 0),
        ("max_tool_calls", 0),
        ("max_retries", 0),
        ("tool_timeout_seconds", 0),
    ],
)
def test_invalid_loop_counter_or_limit_is_rejected(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        OpsAgentState(loop={field: value})


@pytest.mark.parametrize(
    "artifact_ref",
    [None, "artifact://logs/query-42"],
)
def test_evidence_accepts_optional_artifact_reference(
    artifact_ref: str | None,
) -> None:
    evidence = EvidenceItem(
        source="synthetic_log_search",
        summary="The relevant log slice contains five errors.",
        key_fields={"error_count": 5},
        metadata={"query_id": "query-42"},
        artifact_ref=artifact_ref,
        timestamp=datetime(2026, 8, 30, 9, 30, tzinfo=UTC),
    )

    assert evidence.artifact_ref == artifact_ref


def test_mutable_defaults_are_isolated_between_root_states() -> None:
    first = OpsAgentState()
    second = OpsAgentState()

    first.identity.roles.append("operator")
    first.identity.source_context["channel"] = "support_portal"
    first.understanding.entities["system"] = "MES"
    first.task.constraints.append("read-only")
    first.facts.confirmed.append("HTTP 500 was observed.")
    first.evidence.items.append(
        EvidenceItem(
            source="synthetic_log_search",
            summary="One relevant error was found.",
            timestamp=datetime(2026, 8, 30, 9, 30, tzinfo=UTC),
        )
    )
    first.tool.arguments["site_id"] = "SITE-SH-01"

    assert second.identity.roles == []
    assert second.identity.source_context == {}
    assert second.understanding.entities == {}
    assert second.task.constraints == []
    assert second.facts.confirmed == []
    assert second.evidence.items == []
    assert second.tool.arguments == {}


def test_mutable_defaults_are_isolated_between_evidence_items() -> None:
    observed_at = datetime(2026, 8, 30, 9, 30, tzinfo=UTC)
    first = EvidenceItem(source="log_search", summary="first", timestamp=observed_at)
    second = EvidenceItem(source="log_search", summary="second", timestamp=observed_at)

    first.key_fields["event_count"] = 1
    first.metadata["query_id"] = "query-42"

    assert second.key_fields == {}
    assert second.metadata == {}


@pytest.mark.parametrize(
    "payload",
    [
        {"identity": {"roles": {"operator": True}}},
        {"understanding": {"entities": ["MES"]}},
        {"facts": {"confirmed": "HTTP 500 was observed."}},
        {"evidence": {"items": [{"source": "log_search", "summary": "x"}]}},
        {"tool": {"arguments": {"request": object()}}},
        {"safety": []},
    ],
)
def test_invalid_nested_data_is_rejected(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        OpsAgentState.model_validate(payload)


def test_invalid_assignment_is_rejected_after_construction() -> None:
    state = OpsAgentState()

    with pytest.raises(ValidationError):
        state.loop.max_rounds = 0


def test_json_serialization_round_trip_preserves_typed_state() -> None:
    observed_at = datetime(2026, 8, 30, 9, 30, tzinfo=UTC)
    state = OpsAgentState(
        understanding={
            "primary_intent": PrimaryIntent.ACCESS_ISSUE,
            "request_type": RequestType.CHECK_STATUS,
            "risk_signal": RiskSignal.PRIVILEGED_CHANGE,
        },
        evidence={
            "items": [
                {
                    "source": "permission_query",
                    "summary": "The requested menu is not assigned.",
                    "key_fields": {"assigned": False},
                    "artifact_ref": "artifact://permissions/query-7",
                    "timestamp": observed_at,
                }
            ]
        },
        decision={"action": AgentAction.REPLY},
    )

    serialized = state.model_dump_json()
    restored = OpsAgentState.model_validate_json(serialized)

    assert restored == state
    assert restored.evidence.items[0].timestamp == observed_at
    assert json.loads(serialized)["safety"]["capability"] == "READ_ONLY"


def test_non_finite_tool_timeout_is_rejected_before_json_serialization() -> None:
    with pytest.raises(ValidationError):
        OpsAgentState(loop={"tool_timeout_seconds": float("inf")})


def test_tool_state_rejects_raw_result_field() -> None:
    with pytest.raises(ValidationError) as error:
        OpsAgentState(
            tool={
                "selected_tool": "log_search",
                "arguments": {"site_id": "SITE-SH-01"},
                "raw_result": {"events": ["large", "payload"]},
            }
        )

    assert "raw_result" in str(error.value)
