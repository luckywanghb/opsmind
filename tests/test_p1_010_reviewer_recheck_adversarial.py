"""Independent reviewer recheck attacks for TASK-P1-010 remediation."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from opsmind.api.app import create_app
from opsmind.api.runtime import OpsAgentRuntime
from opsmind.api.settings import RuntimeSettings
from opsmind.conversations import (
    ConversationIdentityConflictError,
    ConversationPersistenceService,
    SQLiteConversationRepository,
)
from opsmind.models import MockModelProvider, ModelGateway, ModelProfile, ModelRoute
from opsmind.state import OpsAgentState, TaskStatus


def _service(tmp_path: Path) -> ConversationPersistenceService:
    return ConversationPersistenceService(
        SQLiteConversationRepository(tmp_path / "opsmind.db")
    )


def test_unresolved_p0_uses_recent_unique_chronological_projection(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    lease = service.begin(
        thread_id="unresolved-boundary",
        user_id="U1",
        message="initial",
        request_id="request-1",
        run_id="run-1",
    )
    state = OpsAgentState(
        conversation={"current_query": "continue"},
        task={"status": TaskStatus.WAITING_USER},
        facts={
            "unresolved_questions": [
                *[f"question-{index:02d}" for index in range(21)],
                "question-05",
                "current-blocker",
            ]
        },
    )
    try:
        checkpoint = service.checkpoint_for(
            lease,
            state=state,
            assistant_content="provide the current blocker",
        )
        assert len(checkpoint.unresolved_questions) == 20
        assert checkpoint.unresolved_questions[-1] == "current-blocker"
        assert checkpoint.unresolved_questions.count("question-05") == 1
        assert checkpoint.unresolved_questions == [
            "question-02",
            "question-03",
            "question-04",
            *[f"question-{index:02d}" for index in range(6, 21)],
            "question-05",
            "current-blocker",
        ]
    finally:
        service.fail(lease)


def test_site_restore_is_allowlisted_and_explicit_identity_beats_model_guess(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    first = service.begin(
        thread_id="site-allowlist",
        user_id="U1",
        message="initial",
        request_id="request-1",
        run_id="run-1",
    )
    state = service.build_fresh_state(
        first,
        message="initial",
        source_context={
            "user_id": "U1",
            "site_id": "SITE-EXPLICIT",
            "private": "MUST_NOT_BE_RESTORED",
        },
    )
    state.understanding.entities["site_id"] = "SITE-MODEL-GUESS"
    state.task.status = TaskStatus.WAITING_USER
    service.complete(first, state=state, assistant_content="continue")

    second = service.begin(
        thread_id="site-allowlist",
        user_id="U1",
        message="follow-up",
        request_id="request-2",
        run_id="run-2",
    )
    try:
        restored = service.build_fresh_state(
            second,
            message="follow-up",
            source_context={"user_id": "U1", "current": "CURRENT-ONLY"},
        )
        assert restored.identity.site_id == "SITE-EXPLICIT"
        assert restored.identity.source_context == {
            "user_id": "U1",
            "site_id": "SITE-EXPLICIT",
            "current": "CURRENT-ONLY",
        }
        assert restored.conversation.important_entities["site_id"] == (
            "SITE-EXPLICIT"
        )
        assert "MUST_NOT_BE_RESTORED" not in restored.model_dump_json()
        assert "SITE-MODEL-GUESS" not in restored.model_dump_json()
    finally:
        service.fail(second)


def test_explicit_site_conflict_does_not_advance_checkpoint(tmp_path: Path) -> None:
    service = _service(tmp_path)
    first = service.begin(
        thread_id="site-conflict",
        user_id="U1",
        message="initial",
        request_id="request-1",
        run_id="run-1",
    )
    state = service.build_fresh_state(
        first,
        message="initial",
        source_context={"user_id": "U1", "site_id": "SITE-A"},
    )
    state.task.status = TaskStatus.WAITING_USER
    service.complete(first, state=state, assistant_content="continue")
    before = service.get("site-conflict").checkpoint

    conflicting = service.begin(
        thread_id="site-conflict",
        user_id="U1",
        message="other site",
        request_id="request-2",
        run_id="run-2",
    )
    with pytest.raises(ConversationIdentityConflictError):
        service.build_fresh_state(
            conflicting,
            message="other site",
            source_context={"user_id": "U1", "site_id": "SITE-B"},
        )
    service.fail(conflicting)

    after = service.get("site-conflict")
    assert after.checkpoint == before
    assert after.thread.active_run_id is None


def test_oversized_site_identity_fails_safely_before_conversation_and_provider(
    tmp_path: Path,
) -> None:
    """The durable identity contract must reject rather than truncate."""

    provider = MockModelProvider(structured_responses=[], responses=[])
    runtime = OpsAgentRuntime(
        ModelGateway(
            routes={
                ModelProfile.CHEAP: ModelRoute(
                    profile=ModelProfile.CHEAP,
                    provider="mock",
                    model="reviewer-site-boundary",
                )
            },
            providers={"mock": provider},
        )
    )
    database = tmp_path / "opsmind.db"
    client = TestClient(
        create_app(
            runtime=runtime,
            settings=RuntimeSettings(run_store_path=database),
        ),
        raise_server_exceptions=False,
    )
    site_id = "S" * 513
    response = client.post(
        "/api/v1/chat",
        json={
            "message": "initial",
            "thread_id": "oversized-site",
            "source_context": {"user_id": "U1", "site_id": site_id},
        },
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == (
        "CONVERSATION_PERSISTENCE_UNAVAILABLE"
    )
    assert site_id not in response.text
    assert provider.invocation_count == 0
    runs = client.get("/api/v1/runs").json()
    assert len(runs) == 1
    assert runs[0]["lifecycle_status"] == "FAILED"
    assert client.get("/api/v1/threads").json() == []

    connection = sqlite3.connect(database)
    try:
        for table in (
            "conversation_threads",
            "conversation_turns",
            "conversation_checkpoints",
        ):
            assert connection.execute(f"SELECT count(*) FROM {table}").fetchone() == (
                0,
            )
    finally:
        connection.close()


def test_site_identity_at_512_boundary_is_preserved_exactly_across_runs(
    tmp_path: Path,
) -> None:
    database = tmp_path / "boundary.db"
    client = TestClient(
        create_app(settings=RuntimeSettings(run_store_path=database)),
        raise_server_exceptions=False,
    )
    site_id = "S" * 512
    first = client.post(
        "/api/v1/chat",
        json={
            "message": "initial",
            "thread_id": "boundary-site",
            "source_context": {"user_id": "U1", "site_id": site_id},
        },
    )
    assert first.status_code == 200
    second = client.post(
        "/api/v1/chat",
        json={
            "message": "follow-up",
            "thread_id": "boundary-site",
            "source_context": {"user_id": "U1", "site_id": site_id},
        },
    )
    assert second.status_code == 200
    detail = client.get("/api/v1/threads/boundary-site").json()
    assert detail["checkpoint"]["site_id"] == site_id
    assert detail["checkpoint"]["important_entities"]["site_id"] == site_id
