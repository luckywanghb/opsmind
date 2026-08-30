"""Regression tests for finite JSON and compact evidence boundaries."""

import math
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from opsmind import EvidenceItem, OpsAgentState
from opsmind.state import (
    EVIDENCE_MAX_COLLECTION_ITEMS,
    EVIDENCE_MAX_NESTING_DEPTH,
    EVIDENCE_MAX_SERIALIZED_BYTES,
    EVIDENCE_MAX_STRING_LENGTH,
    EVIDENCE_STATE_MAX_ITEMS,
    EVIDENCE_STATE_MAX_SERIALIZED_BYTES,
)


@pytest.mark.parametrize(
    "payload",
    [
        {"identity": {"source_context": {"nested": [math.inf]}}},
        {"understanding": {"entities": {"score": math.nan}}},
        {
            "evidence": {
                "items": [
                    {
                        "source": "log_search",
                        "summary": "summary",
                        "key_fields": {"count": -math.inf},
                        "timestamp": "2026-08-30T09:30:00Z",
                    }
                ]
            }
        },
        {"tool": {"arguments": {"filters": {"score": math.inf}}}},
    ],
)
def test_all_json_state_fields_reject_non_finite_numbers(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        OpsAgentState.model_validate(payload)


@pytest.mark.parametrize(
    "key",
    [
        "raw_material_id",
        "raw_catalog_id",
        "raw_material_result",
        "data_source",
        "log_reference",
        "raw_events",
        "verbatim_tool_output",
        "draw_result",
    ],
)
def test_evidence_compactness_is_independent_of_business_key_names(key: str) -> None:
    evidence = EvidenceItem(
        source="inventory_search",
        summary="summary",
        key_fields={key: "synthetic-value"},
        timestamp=datetime(2026, 8, 30, 9, 30, tzinfo=UTC),
    )

    assert evidence.key_fields[key] == "synthetic-value"


def test_evidence_rejects_oversized_nested_collection() -> None:
    with pytest.raises(ValidationError):
        EvidenceItem(
            source="log_search",
            summary="summary",
            key_fields={"events": list(range(EVIDENCE_MAX_COLLECTION_ITEMS + 1))},
            timestamp=datetime(2026, 8, 30, 9, 30, tzinfo=UTC),
        )


def test_evidence_rejects_excessive_nesting_depth() -> None:
    nested: object = "value"
    for _ in range(EVIDENCE_MAX_NESTING_DEPTH):
        nested = {"level": nested}

    with pytest.raises(ValidationError):
        EvidenceItem(
            source="log_search",
            summary="summary",
            key_fields={"nested": nested},
            timestamp=datetime(2026, 8, 30, 9, 30, tzinfo=UTC),
        )


def test_evidence_rejects_oversized_nested_string() -> None:
    with pytest.raises(ValidationError):
        EvidenceItem(
            source="log_search",
            summary="summary",
            metadata={"excerpt": "x" * (EVIDENCE_MAX_STRING_LENGTH + 1)},
            timestamp=datetime(2026, 8, 30, 9, 30, tzinfo=UTC),
        )


def test_evidence_rejects_oversized_serialized_item() -> None:
    chunk = "x" * EVIDENCE_MAX_STRING_LENGTH
    with pytest.raises(ValidationError) as error:
        EvidenceItem(
            source="log_search",
            summary=chunk,
            key_fields={f"field_{index}": chunk for index in range(8)},
            timestamp=datetime(2026, 8, 30, 9, 30, tzinfo=UTC),
        )

    assert str(EVIDENCE_MAX_SERIALIZED_BYTES) in str(error.value)


def test_boundary_revalidation_catches_in_place_container_mutation() -> None:
    state = OpsAgentState()
    state.identity.source_context["score"] = math.inf

    with pytest.raises(ValidationError):
        OpsAgentState.model_validate(state)


def _small_evidence_item(index: int) -> dict[str, object]:
    return {
        "source": "log_search",
        "summary": f"compact evidence {index}",
        "timestamp": "2026-08-30T09:30:00Z",
    }


def test_evidence_state_rejects_too_many_items_during_construction() -> None:
    items = [
        _small_evidence_item(index) for index in range(EVIDENCE_STATE_MAX_ITEMS + 1)
    ]

    with pytest.raises(ValidationError):
        OpsAgentState(evidence={"items": items})


def test_evidence_state_rejects_aggregate_serialized_budget() -> None:
    item_count = EVIDENCE_STATE_MAX_SERIALIZED_BYTES // EVIDENCE_MAX_STRING_LENGTH + 1
    items = [
        {
            "source": "log_search",
            "summary": "x" * EVIDENCE_MAX_STRING_LENGTH,
            "timestamp": "2026-08-30T09:30:00Z",
        }
        for _ in range(item_count)
    ]

    assert item_count <= EVIDENCE_STATE_MAX_ITEMS
    with pytest.raises(ValidationError) as error:
        OpsAgentState(evidence={"items": items})

    assert str(EVIDENCE_STATE_MAX_SERIALIZED_BYTES) in str(error.value)


def test_boundary_revalidation_rejects_mutated_evidence_item_count() -> None:
    state = OpsAgentState(
        evidence={
            "items": [
                _small_evidence_item(index)
                for index in range(EVIDENCE_STATE_MAX_ITEMS)
            ]
        }
    )
    state.evidence.items.append(
        EvidenceItem(
            source="log_search",
            summary="one item too many",
            timestamp=datetime(2026, 8, 30, 9, 30, tzinfo=UTC),
        )
    )

    with pytest.raises(ValidationError):
        OpsAgentState.model_validate(state)


def test_evidence_state_accepts_legal_item_count_boundary() -> None:
    state = OpsAgentState(
        evidence={
            "items": [
                _small_evidence_item(index)
                for index in range(EVIDENCE_STATE_MAX_ITEMS)
            ]
        }
    )

    assert len(state.evidence.items) == EVIDENCE_STATE_MAX_ITEMS
