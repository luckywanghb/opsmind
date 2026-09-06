"""Independent adversarial acceptance tests for TASK-P1-010."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from opsmind.api.app import create_app
from opsmind.api.settings import RuntimeSettings
from opsmind.conversations import (
    ConversationPersistenceService,
    SQLiteConversationRepository,
)
from opsmind.state import OpsAgentState, TaskStatus


def test_schema_valid_oversized_user_identity_fails_safely_and_closes_run(
    tmp_path: Path,
) -> None:
    """A public request must not strand a STARTED run on identity validation."""

    client = TestClient(
        create_app(settings=RuntimeSettings(run_store_path=tmp_path / "opsmind.db")),
        raise_server_exceptions=False,
    )

    response = client.post(
        "/api/v1/chat",
        json={
            "message": "safe request",
            # ChatRequest accepts this FiniteJsonObject, while the conversation
            # domain caps a persisted user identity at 512 characters.
            "source_context": {"user_id": "U" * 513},
        },
    )

    runs = client.get("/api/v1/runs").json()
    assert len(runs) == 1
    assert (response.status_code, runs[0]["lifecycle_status"]) in {
        (422, "FAILED"),
        (503, "FAILED"),
    }


def test_checkpoint_budget_preserves_new_critical_business_entity(
    tmp_path: Path,
) -> None:
    """P0 business identifiers must survive a full entity checkpoint budget."""

    service = ConversationPersistenceService(
        SQLiteConversationRepository(tmp_path / "opsmind.db")
    )
    lease = service.begin(
        thread_id="entity-budget-thread",
        user_id="U1",
        message="initial problem",
        request_id="request-1",
        run_id="run-1",
    )
    state = OpsAgentState(
        conversation={
            "thread_id": lease.thread_id,
            "original_query": "initial problem",
            "current_query": "the identifier is WO20260001",
        },
        understanding={
            # A structured model output may contain other scalar entities; the
            # critical identifier is deliberately placed after the capacity.
            "entities": {
                **{f"auxiliary_{index}": index for index in range(20)},
                "work_order_id": "WO20260001",
            }
        },
        task={"status": TaskStatus.WAITING_USER},
    )
    try:
        checkpoint = service.checkpoint_for(
            lease,
            state=state,
            assistant_content="Please continue.",
        )
        assert checkpoint.important_entities["work_order_id"] == "WO20260001"
    finally:
        service.fail(lease)
