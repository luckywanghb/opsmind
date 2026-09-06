"""Persistence, transaction, isolation, and bounded-context tests."""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from opsmind.conversations import (
    ConversationCheckpoint,
    ConversationConflictError,
    ConversationIdentityConflictError,
    ConversationLease,
    ConversationPersistenceError,
    ConversationPersistenceService,
    ConversationStatus,
    ConversationTurn,
    IncompatibleConversationSchemaError,
    SQLiteConversationRepository,
)
from opsmind.state import (
    OpsAgentState,
    PrimaryIntent,
    RequestType,
    ResolutionStatus,
    TaskStatus,
)


def _checkpoint(
    lease: ConversationLease, *, revision: int, run_id: str
) -> ConversationCheckpoint:
    return ConversationCheckpoint(
        thread_id=lease.thread_id,
        revision=revision,
        original_query=lease.context.thread.original_query,
        previous_resolution_status=ResolutionStatus.UNRESOLVED,
        task_objective="diagnose work order",
        confirmed_facts=["work order identifier supplied"],
        unresolved_questions=["who handles it now"],
        latest_understanding_summary="workflow continuation",
        important_entities={"work_order_id": "WO20260001"},
        last_assistant_message="Which work order?",
        latest_run_id=run_id,
        updated_at=datetime.now(UTC),
    )


def _begin(
    repository: SQLiteConversationRepository,
    *,
    thread_id: str = "thread-1",
    request_id: str = "request-1",
    run_id: str = "run-1",
    message: str = "first question",
    user_id: str | None = None,
):
    return repository.begin_run(
        thread_id=thread_id,
        user_id=user_id,
        message=message,
        request_id=request_id,
        run_id=run_id,
        recent_turn_limit=6,
    )


def _complete(
    repository: SQLiteConversationRepository, lease: ConversationLease
) -> None:
    repository.complete_run(
        lease,
        assistant_content="safe reply",
        checkpoint=_checkpoint(
            lease,
            revision=lease.revision + 1,
            run_id=lease.run_id,
        ),
        status=ConversationStatus.WAITING_USER,
        previous_resolution_status=ResolutionStatus.UNRESOLVED,
    )


def test_schema_initialization_is_idempotent_and_versioned(tmp_path: Path) -> None:
    path = tmp_path / "opsmind.db"
    first = SQLiteConversationRepository(path)
    _begin(first)
    second = SQLiteConversationRepository(path)
    assert second.get("thread-1") is not None

    connection = sqlite3.connect(path)
    try:
        value = connection.execute(
            """SELECT value FROM conversation_schema_metadata
               WHERE key = 'schema_version'"""
        ).fetchone()
    finally:
        connection.close()
    assert value == ("1",)


def test_unsupported_schema_version_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "opsmind.db"
    repository = SQLiteConversationRepository(path)
    _begin(repository)
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            """UPDATE conversation_schema_metadata SET value = '999'
               WHERE key = 'schema_version'"""
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(IncompatibleConversationSchemaError):
        SQLiteConversationRepository(path).get("thread-1")


def test_create_append_reload_order_revision_and_listing(tmp_path: Path) -> None:
    repository = SQLiteConversationRepository(tmp_path / "opsmind.db")
    lease = _begin(repository, user_id="U1")
    assert lease.context.checkpoint is None
    assert lease.context.recent_turns == []
    _complete(repository, lease)

    second = _begin(
        repository,
        request_id="request-2",
        run_id="run-2",
        message="follow up",
        user_id="U1",
    )
    assert second.context.checkpoint is not None
    assert second.context.checkpoint.important_entities == {
        "work_order_id": "WO20260001"
    }
    assert [turn.sequence for turn in second.context.recent_turns] == [1, 2]
    assert [turn.role.value for turn in second.context.recent_turns] == [
        "USER",
        "ASSISTANT",
    ]
    _complete(repository, second)

    detail = repository.get("thread-1")
    assert detail is not None
    assert detail.thread.turn_count == 4
    assert detail.thread.revision == 4
    assert [turn.sequence for turn in detail.turns] == [1, 2, 3, 4]
    assert [turn.run_id for turn in detail.turns] == [
        "run-1",
        "run-1",
        "run-2",
        "run-2",
    ]
    assert repository.list(limit=50)[0].thread_id == "thread-1"


def test_cross_thread_isolation_and_identity_fail_closed(tmp_path: Path) -> None:
    repository = SQLiteConversationRepository(tmp_path / "opsmind.db")
    first = _begin(repository, thread_id="A", user_id="U-A")
    _complete(repository, first)
    other = _begin(
        repository,
        thread_id="B",
        request_id="request-B",
        run_id="run-B",
        message="unrelated",
        user_id="U-B",
    )
    assert other.context.checkpoint is None
    assert other.context.recent_turns == []
    repository.fail_run(other)

    with pytest.raises(ConversationIdentityConflictError):
        _begin(
            repository,
            thread_id="A",
            request_id="request-X",
            run_id="run-X",
            message="steal context",
            user_id="U-B",
        )


def test_active_run_rejects_cross_instance_lost_update(tmp_path: Path) -> None:
    path = tmp_path / "opsmind.db"
    first_repository = SQLiteConversationRepository(path)
    second_repository = SQLiteConversationRepository(path)
    lease = _begin(first_repository)

    with pytest.raises(ConversationConflictError):
        _begin(
            second_repository,
            request_id="request-2",
            run_id="run-2",
            message="concurrent",
        )

    first_repository.fail_run(lease)


@pytest.mark.asyncio
async def test_service_serializes_same_thread_but_not_different_threads(
    tmp_path: Path,
) -> None:
    service = ConversationPersistenceService(
        SQLiteConversationRepository(tmp_path / "opsmind.db")
    )
    active = 0
    maximum = 0

    async def enter(thread_id: str) -> None:
        nonlocal active, maximum
        async with service.serialized(thread_id):
            active += 1
            maximum = max(maximum, active)
            await asyncio.sleep(0.01)
            active -= 1

    await asyncio.gather(enter("same"), enter("same"))
    assert maximum == 1

    maximum = 0
    await asyncio.gather(enter("A"), enter("B"))
    assert maximum == 2


class _FailAssistantRepository(SQLiteConversationRepository):
    @staticmethod
    def _insert_turn(
        connection: sqlite3.Connection, turn: ConversationTurn
    ) -> None:
        if turn.role.value == "ASSISTANT":
            raise sqlite3.OperationalError("TRACEBACK_SECRET_SENTINEL")
        SQLiteConversationRepository._insert_turn(connection, turn)


def test_assistant_failure_rolls_back_checkpoint_and_turn(tmp_path: Path) -> None:
    repository = _FailAssistantRepository(tmp_path / "opsmind.db")
    lease = _begin(repository)

    with pytest.raises(ConversationPersistenceError):
        _complete(repository, lease)

    detail = repository.get("thread-1")
    assert detail is not None
    assert len(detail.turns) == 1
    assert detail.checkpoint is None


def test_checkpoint_failure_rolls_back_assistant_turn(tmp_path: Path) -> None:
    path = tmp_path / "opsmind.db"
    repository = SQLiteConversationRepository(path)
    lease = _begin(repository)
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            """CREATE TRIGGER reject_checkpoint BEFORE INSERT
               ON conversation_checkpoints BEGIN
               SELECT RAISE(ABORT, 'TRACEBACK_SECRET_SENTINEL'); END"""
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(ConversationPersistenceError):
        _complete(repository, lease)

    detail = repository.get("thread-1")
    assert detail is not None
    assert len(detail.turns) == 1
    assert detail.checkpoint is None


def test_failed_run_keeps_user_turn_without_fake_assistant_or_checkpoint(
    tmp_path: Path,
) -> None:
    repository = SQLiteConversationRepository(tmp_path / "opsmind.db")
    lease = _begin(repository)
    repository.fail_run(lease)

    detail = repository.get("thread-1")
    assert detail is not None
    assert [turn.role.value for turn in detail.turns] == ["USER"]
    assert detail.checkpoint is None
    assert detail.thread.active_run_id is None


def test_many_turns_are_durable_while_restored_context_is_bounded(
    tmp_path: Path,
) -> None:
    repository = SQLiteConversationRepository(tmp_path / "opsmind.db")
    service = ConversationPersistenceService(repository)
    for index in range(30):
        lease = service.begin(
            thread_id="long-thread",
            user_id="U1",
            message=f"turn {index}",
            request_id=f"request-{index}",
            run_id=f"run-{index}",
        )
        state = OpsAgentState(
            conversation={
                "thread_id": "long-thread",
                "original_query": "turn 0",
                "current_query": f"turn {index}",
            },
            understanding={
                "primary_intent": PrimaryIntent.WORKFLOW_ISSUE,
                "request_type": RequestType.CONTINUE_CASE,
                "entities": {"work_order_id": "WO20260001"},
            },
            task={"status": TaskStatus.WAITING_USER},
            facts={"unresolved_questions": ["who handles it now"]},
        )
        service.complete(lease, state=state, assistant_content=f"reply {index}")

    final = service.begin(
        thread_id="long-thread",
        user_id="U1",
        message="current query",
        request_id="request-final",
        run_id="run-final",
    )
    restored = service.build_fresh_state(
        final,
        message="current query",
        source_context={"user_id": "U1"},
    )
    detail = repository.get("long-thread")
    assert detail is not None
    assert detail.thread.turn_count == 61
    assert len(restored.conversation.recent_turns) == 6
    assert restored.conversation.original_query == "turn 0"
    assert restored.conversation.current_query == "current query"
    assert restored.conversation.important_entities["work_order_id"] == "WO20260001"
    assert restored.facts.unresolved_questions == ["who handles it now"]
    service.fail(final)
