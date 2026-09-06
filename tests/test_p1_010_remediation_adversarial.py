"""Independent remediation attacks for TASK-P1-010."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from pathlib import Path

from fastapi.testclient import TestClient

from opsmind.api.app import create_app
from opsmind.api.settings import RuntimeSettings
from opsmind.conversations import (
    ConversationPersistenceService,
    SQLiteConversationRepository,
)
from opsmind.state import OpsAgentState, TaskStatus


def _checkpoint_entities(
    tmp_path: Path,
    *,
    thread_id: str,
    current: Mapping[str, str | int | bool],
    previous: Mapping[str, str | int | bool] | None = None,
) -> dict[str, str | int | bool]:
    service = ConversationPersistenceService(
        SQLiteConversationRepository(tmp_path / f"{thread_id}.db")
    )
    lease = service.begin(
        thread_id=thread_id,
        user_id="U1",
        message="initial",
        request_id=f"request-{thread_id}",
        run_id=f"run-{thread_id}",
    )
    if previous:
        prior_state = OpsAgentState(
            conversation={"current_query": "initial"},
            understanding={"entities": dict(previous)},
            task={"status": TaskStatus.WAITING_USER},
        )
        service.complete(lease, state=prior_state, assistant_content="continue")
        lease = service.begin(
            thread_id=thread_id,
            user_id="U1",
            message="follow up",
            request_id=f"request-{thread_id}-2",
            run_id=f"run-{thread_id}-2",
        )
    state = OpsAgentState(
        conversation={"current_query": "follow up"},
        understanding={"entities": dict(current)},
        task={"status": TaskStatus.WAITING_USER},
    )
    try:
        checkpoint = service.checkpoint_for(
            lease, state=state, assistant_content="continue"
        )
        return dict(checkpoint.important_entities)
    finally:
        service.fail(lease)


def test_oversized_identity_is_safe_failed_run_with_no_conversation_residue(
    tmp_path: Path,
) -> None:
    database = tmp_path / "opsmind.db"
    client = TestClient(
        create_app(settings=RuntimeSettings(run_store_path=database)),
        raise_server_exceptions=False,
    )

    response = client.post(
        "/api/v1/chat",
        json={"message": "safe", "source_context": {"user_id": "U" * 513}},
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "CONVERSATION_PERSISTENCE_UNAVAILABLE"
    runs = client.get("/api/v1/runs").json()
    assert len(runs) == 1
    assert runs[0]["lifecycle_status"] == "FAILED"
    assert client.get("/api/v1/threads").json() == []
    assert "U" * 513 not in response.text
    connection = sqlite3.connect(database)
    try:
        assert connection.execute(
            "SELECT count(*) FROM conversation_threads"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM conversation_turns"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM conversation_checkpoints"
        ).fetchone() == (0,)
    finally:
        connection.close()


def test_entity_ranking_is_order_independent_for_distinct_keys(tmp_path: Path) -> None:
    entries = {
        **{f"noise_{index:02d}": index for index in range(30)},
        "asset_id": "ASSET-1",
        "incident_id": "INC-1",
    }
    forward = _checkpoint_entities(
        tmp_path, thread_id="forward", current=entries
    )
    reverse = _checkpoint_entities(
        tmp_path,
        thread_id="reverse",
        current=dict(reversed(list(entries.items()))),
    )

    assert forward == reverse
    assert forward["asset_id"] == "ASSET-1"
    assert forward["incident_id"] == "INC-1"


def test_historical_identifier_survives_current_non_identifier_noise(
    tmp_path: Path,
) -> None:
    result = _checkpoint_entities(
        tmp_path,
        thread_id="history",
        previous={"asset_id": "ASSET-HISTORICAL"},
        current={f"noise_{index:02d}": index for index in range(40)},
    )

    assert result["asset_id"] == "ASSET-HISTORICAL"


def test_entity_ranking_has_total_order_for_case_variant_identifier_keys(
    tmp_path: Path,
) -> None:
    """Equivalent candidate sets must not fall back to mapping insertion order."""

    variants = {
        **{f"a{index:02d}_id": f"VALUE-{index}" for index in range(19)},
        "TARGET_ID": "UPPER-VALUE",
        "target_id": "LOWER-VALUE",
    }
    forward = _checkpoint_entities(
        tmp_path, thread_id="case-forward", current=variants
    )
    reverse = _checkpoint_entities(
        tmp_path,
        thread_id="case-reverse",
        current=dict(reversed(list(variants.items()))),
    )

    assert forward == reverse


def test_long_entity_key_collision_has_order_independent_winner(
    tmp_path: Path,
) -> None:
    """Two valid long keys with one bounded prefix need one stable winner."""

    bounded_key = f"{'x' * 248}asset_id"
    assert len(bounded_key) == 256
    entries = {
        f"{bounded_key}-B": "LEXICALLY-LATER",
        f"{bounded_key}-A": "LEXICALLY-EARLIER",
    }
    forward = _checkpoint_entities(
        tmp_path, thread_id="long-forward", current=entries
    )
    reverse = _checkpoint_entities(
        tmp_path,
        thread_id="long-reverse",
        current=dict(reversed(list(entries.items()))),
    )

    assert forward == reverse
    assert forward == {bounded_key: "LEXICALLY-EARLIER"}
