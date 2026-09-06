"""Reviewer-only adversarial checks for TASK-P1-010."""

from __future__ import annotations

from pathlib import Path

from opsmind.conversations import (
    ConversationPersistenceService,
    SQLiteConversationRepository,
)
from opsmind.state import OpsAgentState, TaskStatus


def _service(tmp_path: Path) -> ConversationPersistenceService:
    return ConversationPersistenceService(
        SQLiteConversationRepository(tmp_path / "opsmind.db")
    )


def test_checkpoint_retains_new_p0_unresolved_question_when_budget_is_full(
    tmp_path: Path,
) -> None:
    """Current blockers must not be evicted by older unresolved questions."""

    service = _service(tmp_path)
    lease = service.begin(
        thread_id="unresolved-priority",
        user_id="U1",
        message="initial problem",
        request_id="request-1",
        run_id="run-1",
    )
    current_blocker = "current run requires the equipment identifier"
    state = OpsAgentState(
        conversation={"current_query": "continue"},
        task={"status": TaskStatus.WAITING_USER},
        facts={
            "unresolved_questions": [
                *[f"older unresolved question {index}" for index in range(20)],
                current_blocker,
            ]
        },
    )
    try:
        checkpoint = service.checkpoint_for(
            lease,
            state=state,
            assistant_content="Please provide the equipment identifier.",
        )
        assert current_blocker in checkpoint.unresolved_questions
    finally:
        service.fail(lease)


def test_safe_site_identity_is_restored_when_followup_omits_source_context(
    tmp_path: Path,
) -> None:
    """A same-thread fresh run should retain its explicit site scope."""

    service = _service(tmp_path)
    first = service.begin(
        thread_id="site-continuity",
        user_id="U1",
        message="the site is unavailable",
        request_id="request-1",
        run_id="run-1",
    )
    first_state = service.build_fresh_state(
        first,
        message="the site is unavailable",
        source_context={"user_id": "U1", "site_id": "SITE-A"},
    )
    first_state.task.status = TaskStatus.WAITING_USER
    service.complete(
        first,
        state=first_state,
        assistant_content="Which symptom do you see?",
    )

    second = service.begin(
        thread_id="site-continuity",
        user_id="U1",
        message="HTTP 500",
        request_id="request-2",
        run_id="run-2",
    )
    try:
        restored = service.build_fresh_state(
            second,
            message="HTTP 500",
            source_context={"user_id": "U1"},
        )
        assert restored.identity.site_id == "SITE-A"
    finally:
        service.fail(second)
