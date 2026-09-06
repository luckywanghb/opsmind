"""Final Independent Tester boundary evidence for TASK-P1-010."""

from __future__ import annotations

from pathlib import Path

import pytest

from opsmind.conversations import (
    ConversationDataIntegrityError,
    ConversationIdentityConflictError,
    SQLiteConversationRepository,
)


def test_user_identity_512_is_lossless_and_513_rolls_back(tmp_path: Path) -> None:
    repository = SQLiteConversationRepository(tmp_path / "identity.db")
    accepted_user = "U" * 512
    lease = repository.begin_run(
        thread_id="accepted",
        user_id=accepted_user,
        message="initial",
        request_id="request-accepted",
        run_id="run-accepted",
        recent_turn_limit=6,
    )
    accepted = repository.get("accepted")
    assert accepted is not None
    assert accepted.thread.user_id == accepted_user
    repository.fail_run(lease)

    with pytest.raises(ConversationDataIntegrityError):
        repository.begin_run(
            thread_id="rejected",
            user_id="U" * 513,
            message="initial",
            request_id="request-rejected",
            run_id="run-rejected",
            recent_turn_limit=6,
        )
    assert repository.get("rejected") is None


def test_bound_user_identity_rejects_omission_to_different_explicit_user(
    tmp_path: Path,
) -> None:
    repository = SQLiteConversationRepository(tmp_path / "user-isolation.db")
    lease = repository.begin_run(
        thread_id="private-thread",
        user_id="U-A",
        message="private",
        request_id="request-a",
        run_id="run-a",
        recent_turn_limit=6,
    )
    repository.fail_run(lease)

    with pytest.raises(ConversationIdentityConflictError):
        repository.begin_run(
            thread_id="private-thread",
            user_id="U-B",
            message="steal",
            request_id="request-b",
            run_id="run-b",
            recent_turn_limit=6,
        )
    detail = repository.get("private-thread")
    assert detail is not None
    assert detail.thread.user_id == "U-A"
    assert [turn.content for turn in detail.turns] == ["private"]
