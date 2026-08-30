"""Tester-owned adversarial coverage for JSON and evidence boundaries."""

import math
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from opsmind import EvidenceItem, OpsAgentState
from opsmind.state import (
    EVIDENCE_MAX_COLLECTION_ITEMS,
    EVIDENCE_MAX_STRING_LENGTH,
    EVIDENCE_STATE_MAX_ITEMS,
    EVIDENCE_STATE_MAX_SERIALIZED_BYTES,
)


def _observed_at() -> datetime:
    return datetime(2026, 8, 30, 9, 30, tzinfo=UTC)


@pytest.mark.parametrize(
    "json_field",
    ["source_context", "entities", "key_fields", "metadata", "arguments"],
)
def test_boundary_revalidation_rejects_non_finite_container_mutation(
    json_field: str,
) -> None:
    state = OpsAgentState(
        evidence={
            "items": [
                {
                    "source": "log_search",
                    "summary": "A compact summary.",
                    "timestamp": _observed_at(),
                }
            ]
        }
    )
    json_fields = {
        "source_context": state.identity.source_context,
        "entities": state.understanding.entities,
        "key_fields": state.evidence.items[0].key_fields,
        "metadata": state.evidence.items[0].metadata,
        "arguments": state.tool.arguments,
    }
    json_fields[json_field]["nested"] = [math.inf]

    with pytest.raises(ValidationError):
        OpsAgentState.model_validate(state)


def test_business_key_is_allowed_but_mutated_oversized_payload_is_rejected() -> None:
    state = OpsAgentState(
        evidence={
            "items": [
                {
                    "source": "log_search",
                    "summary": "A compact response summary.",
                    "key_fields": {"raw_api_response": []},
                    "timestamp": _observed_at(),
                }
            ]
        }
    )
    response = state.evidence.items[0].key_fields["raw_api_response"]
    assert isinstance(response, list)
    response.extend(range(EVIDENCE_MAX_COLLECTION_ITEMS + 1))

    with pytest.raises(ValidationError):
        OpsAgentState.model_validate(state)


def test_evidence_rejects_unbounded_item_collection_at_construction() -> None:
    item = {
        "source": "log_search",
        "summary": "One raw log line.",
        "timestamp": _observed_at(),
    }

    with pytest.raises(ValidationError):
        OpsAgentState(
            evidence={
                "items": [item.copy() for _ in range(EVIDENCE_MAX_COLLECTION_ITEMS + 1)]
            }
        )


def test_boundary_revalidation_rejects_unbounded_evidence_item_mutation() -> None:
    state = OpsAgentState()
    for index in range(EVIDENCE_MAX_COLLECTION_ITEMS + 1):
        state.evidence.items.append(
            EvidenceItem(
                source="log_search",
                summary=f"Raw log line {index}.",
                timestamp=_observed_at(),
            )
        )

    with pytest.raises(ValidationError):
        OpsAgentState.model_validate(state)


def test_boundary_revalidation_rejects_aggregate_size_mutation() -> None:
    item_count = 30
    state = OpsAgentState(
        evidence={
            "items": [
                {
                    "source": "log_search",
                    "summary": "x" * EVIDENCE_MAX_STRING_LENGTH,
                    "timestamp": _observed_at(),
                }
                for _ in range(item_count)
            ]
        }
    )
    assert len(state.evidence.model_dump_json().encode("utf-8")) < (
        EVIDENCE_STATE_MAX_SERIALIZED_BYTES
    )
    state.evidence.items.append(
        EvidenceItem(
            source="log_search",
            summary="x" * EVIDENCE_MAX_STRING_LENGTH,
            timestamp=_observed_at(),
        )
    )
    assert len(state.evidence.items) < EVIDENCE_STATE_MAX_ITEMS

    with pytest.raises(ValidationError):
        OpsAgentState.model_validate(state)


def test_compact_json_payload_and_round_trip_remain_supported() -> None:
    state = OpsAgentState(
        identity={
            "source_context": {
                "channel": "support_portal",
                "client": {"version": 2.1, "features": ["chat", "attachments"]},
            }
        },
        understanding={
            "entities": {
                "system": "EquipFlow",
                "sites": ["SITE-SH-01", "SITE-SH-02"],
            }
        },
        evidence={
            "items": [
                {
                    "source": "synthetic_log_search",
                    "summary": "Five recent HTTP 500 events were found.",
                    "key_fields": {
                        "event_count": 5,
                        "raw_material_id": "RM-1001",
                        "raw_material_result": "PASS",
                        "raw_result": "bounded-status-code",
                        "raw_api_response": {"status": 200},
                        "data_source": "synthetic_sensor",
                        "log_reference": "artifact://logs/query-42",
                        "raw_events": ["compact-event-summary"],
                        "verbatim_tool_output": "bounded diagnostic excerpt",
                        "draw_result": "PASS",
                        "service_health": {"available": False, "error_rate": 0.4},
                    },
                    "metadata": {"query_id": "query-42", "page": 1},
                    "artifact_ref": "artifact://logs/query-42",
                    "timestamp": _observed_at(),
                }
            ]
        },
        tool={
            "arguments": {
                "site_id": "SITE-SH-01",
                "filters": {"status": ["OPEN", "INVESTIGATING"]},
            }
        },
    )

    restored = OpsAgentState.model_validate_json(state.model_dump_json())

    assert restored == state
    assert restored.evidence.items[0].key_fields["raw_material_id"] == "RM-1001"
