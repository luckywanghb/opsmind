"""Conversation lifecycle, context restoration, and safe projection service."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from pydantic import JsonValue

from opsmind.conversations.models import (
    MAX_CHECKPOINT_ITEMS,
    MAX_CHECKPOINT_TEXT_LENGTH,
    MAX_IMPORTANT_ENTITIES,
    ConversationCheckpoint,
    ConversationLease,
    ConversationStatus,
    ConversationThread,
    ConversationThreadDetail,
)
from opsmind.conversations.repository import (
    ConversationIdentityConflictError,
    ConversationNotFoundError,
    ConversationRepository,
)
from opsmind.state import (
    ConversationHistoryItem,
    ConversationHistoryRole,
    ConversationState,
    FactsState,
    IdentityState,
    OpsAgentState,
    ResolutionStatus,
    TaskState,
    TaskStatus,
)

RECENT_TURN_LIMIT = 6


def _bounded(
    value: str | None, maximum: int = MAX_CHECKPOINT_TEXT_LENGTH
) -> str | None:
    if value is None:
        return None
    clean = value.strip()
    if not clean:
        return None
    return clean[:maximum]


def _bounded_items(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        item = _bounded(value)
        if item is not None and item not in result:
            result.append(item)
        if len(result) == MAX_CHECKPOINT_ITEMS:
            break
    return result


def _bounded_recent_items(values: list[str]) -> list[str]:
    """Keep the most recent unique P0 items while preserving display order."""

    selected: list[str] = []
    for value in reversed(values):
        item = _bounded(value)
        if item is not None and item not in selected:
            selected.append(item)
        if len(selected) == MAX_CHECKPOINT_ITEMS:
            break
    return list(reversed(selected))


def _important_entities(
    previous: dict[str, str | int | bool], state: OpsAgentState
) -> dict[str, str | int | bool]:
    current_candidates: list[tuple[str, str | int | bool, str]] = []
    for key, value in state.understanding.entities.items():
        if not key:
            continue
        if not isinstance(value, (str, int, bool)):
            continue
        if isinstance(value, str):
            value = value.strip()[:512]
            if not value:
                continue
        current_candidates.append((key[:256], value, key))
    # Keys are bounded for checkpoint storage. If different long input keys
    # share the same bounded prefix, choose a winner by a total lexical order
    # instead of whichever mapping entry happened to arrive last.
    current: dict[str, str | int | bool] = {}
    for bounded_key, value, _original_key in sorted(
        current_candidates,
        key=lambda item: (item[2].casefold(), item[2]),
    ):
        current.setdefault(bounded_key, value)
    if state.identity.site_id is not None:
        site_id = state.identity.site_id.strip()[:512]
        if site_id:
            # Explicit allowlisted identity is authoritative over a model-
            # inferred entity with the same key.
            current["site_id"] = site_id

    def priority(
        item: tuple[str, str | int | bool, int],
    ) -> tuple[int, int, str, str]:
        key = item[0].casefold()
        # Structured identifiers are P0 continuity anchors regardless of the
        # business object or input mapping order. Current-turn values outrank
        # historical values within the same priority class.
        return (
            0 if key == "id" or key.endswith("_id") else 1,
            item[2],
            key,
            item[0],
        )

    candidates = [
        *((key, value, 0) for key, value in current.items()),
        *((key, value, 1) for key, value in previous.items() if key not in current),
    ]
    ranked = sorted(candidates, key=priority)
    return {key: value for key, value, _source in ranked[:MAX_IMPORTANT_ENTITIES]}


def _resolution_status(status: TaskStatus | None) -> ResolutionStatus:
    if status in {TaskStatus.RESOLVED, TaskStatus.CLOSED}:
        return ResolutionStatus.RESOLVED
    if status is TaskStatus.READY_TO_REPLY:
        return ResolutionStatus.PARTIALLY_RESOLVED
    if status in {
        TaskStatus.ACTIVE,
        TaskStatus.WAITING_USER,
        TaskStatus.INVESTIGATING,
        TaskStatus.TRANSFERRED,
    }:
        return ResolutionStatus.UNRESOLVED
    return ResolutionStatus.UNKNOWN


def _conversation_status(status: TaskStatus | None) -> ConversationStatus:
    if status is None:
        return ConversationStatus.ACTIVE
    return {
        TaskStatus.WAITING_USER: ConversationStatus.WAITING_USER,
        TaskStatus.RESOLVED: ConversationStatus.RESOLVED,
        TaskStatus.TRANSFERRED: ConversationStatus.TRANSFERRED,
        TaskStatus.CLOSED: ConversationStatus.CLOSED,
    }.get(status, ConversationStatus.ACTIVE)


class ConversationPersistenceService:
    """Application boundary for durable, bounded conversation continuity."""

    def __init__(self, repository: ConversationRepository) -> None:
        self._repository = repository
        self._locks: dict[str, tuple[asyncio.Lock, int]] = {}
        self._locks_guard = asyncio.Lock()

    @property
    def repository(self) -> ConversationRepository:
        return self._repository

    @asynccontextmanager
    async def serialized(self, thread_id: str) -> AsyncIterator[None]:
        """Serialize one thread in-process; repository ownership guards peers."""

        async with self._locks_guard:
            lock, users = self._locks.get(thread_id, (asyncio.Lock(), 0))
            self._locks[thread_id] = (lock, users + 1)
        await lock.acquire()
        try:
            yield
        finally:
            lock.release()
            async with self._locks_guard:
                current_lock, current_users = self._locks[thread_id]
                if current_users == 1:
                    del self._locks[thread_id]
                else:
                    self._locks[thread_id] = (current_lock, current_users - 1)

    def begin(
        self,
        *,
        thread_id: str,
        user_id: str | None,
        message: str,
        request_id: str,
        run_id: str,
    ) -> ConversationLease:
        return self._repository.begin_run(
            thread_id=thread_id,
            user_id=user_id,
            message=message,
            request_id=request_id,
            run_id=run_id,
            recent_turn_limit=RECENT_TURN_LIMIT,
        )

    def build_fresh_state(
        self,
        lease: ConversationLease,
        *,
        message: str,
        source_context: dict[str, JsonValue],
    ) -> OpsAgentState:
        """Restore conversation-only fields into a new Agent state."""

        checkpoint = lease.context.checkpoint
        thread = lease.context.thread
        explicit_site_id = source_context.get("site_id")
        current_site_id = (
            explicit_site_id if isinstance(explicit_site_id, str) else None
        )
        stored_site_id = checkpoint.site_id if checkpoint is not None else None
        if (
            stored_site_id is not None
            and current_site_id is not None
            and stored_site_id != current_site_id
        ):
            raise ConversationIdentityConflictError(
                "conversation site identity does not match"
            )
        site_id = current_site_id or stored_site_id
        restored_source_context = dict(source_context)
        if site_id is not None:
            restored_source_context["site_id"] = site_id
        if thread.user_id is not None and "user_id" not in restored_source_context:
            restored_source_context["user_id"] = thread.user_id
        recent_turns = [
            ConversationHistoryItem(
                role=ConversationHistoryRole(turn.role.value),
                content=turn.content[-MAX_CHECKPOINT_TEXT_LENGTH:],
            )
            for turn in lease.context.recent_turns
        ]
        return OpsAgentState(
            identity=IdentityState(
                user_id=(
                    source_context.get("user_id")
                    if isinstance(source_context.get("user_id"), str)
                    else thread.user_id
                ),
                site_id=site_id,
                source_context=restored_source_context,
            ),
            conversation=ConversationState(
                thread_id=thread.thread_id,
                original_query=thread.original_query,
                current_query=message,
                summary=(
                    checkpoint.latest_understanding_summary if checkpoint else None
                ),
                previous_resolution_status=(
                    checkpoint.previous_resolution_status
                    if checkpoint
                    else thread.previous_resolution_status
                ),
                recent_turns=recent_turns,
                important_entities=(
                    dict(checkpoint.important_entities) if checkpoint else {}
                ),
                last_assistant_message=(
                    checkpoint.last_assistant_message if checkpoint else None
                ),
            ),
            task=TaskState(
                objective=checkpoint.task_objective if checkpoint else None,
                status=TaskStatus.ACTIVE,
                constraints=(list(checkpoint.task_constraints) if checkpoint else []),
            ),
            facts=FactsState(
                confirmed=(list(checkpoint.confirmed_facts) if checkpoint else []),
                unresolved_questions=(
                    list(checkpoint.unresolved_questions) if checkpoint else []
                ),
            ),
        )

    def checkpoint_for(
        self,
        lease: ConversationLease,
        *,
        state: OpsAgentState,
        assistant_content: str | None,
    ) -> ConversationCheckpoint:
        """Project only typed, bounded conversation-level state."""

        canonical = OpsAgentState.model_validate(state)
        previous = lease.context.checkpoint
        understanding = canonical.understanding
        summary_parts = [
            (
                f"intent={understanding.primary_intent.value}"
                if understanding.primary_intent is not None
                else None
            ),
            (
                f"request_type={understanding.request_type.value}"
                if understanding.request_type is not None
                else None
            ),
            _bounded(understanding.symptom),
        ]
        summary = "; ".join(item for item in summary_parts if item)
        prior_entities = dict(previous.important_entities) if previous else {}
        now = datetime.now(UTC)
        resolution = _resolution_status(canonical.task.status)
        unresolved = (
            []
            if canonical.task.status in {TaskStatus.RESOLVED, TaskStatus.CLOSED}
            else _bounded_recent_items(canonical.facts.unresolved_questions)
        )
        return ConversationCheckpoint(
            thread_id=lease.thread_id,
            revision=lease.revision + 1,
            original_query=lease.context.thread.original_query,
            previous_resolution_status=resolution,
            site_id=_bounded(canonical.identity.site_id, 512),
            task_objective=_bounded(canonical.task.objective),
            task_constraints=_bounded_items(canonical.task.constraints),
            confirmed_facts=_bounded_items(canonical.facts.confirmed),
            unresolved_questions=unresolved,
            latest_understanding_summary=_bounded(summary),
            important_entities=_important_entities(prior_entities, canonical),
            last_assistant_message=(
                _bounded(assistant_content)
                if assistant_content is not None
                else (previous.last_assistant_message if previous is not None else None)
            ),
            latest_run_id=lease.run_id,
            updated_at=now,
        )

    def complete(
        self,
        lease: ConversationLease,
        *,
        state: OpsAgentState,
        assistant_content: str | None,
    ) -> ConversationThread:
        checkpoint = self.checkpoint_for(
            lease, state=state, assistant_content=assistant_content
        )
        return self._repository.complete_run(
            lease,
            assistant_content=assistant_content,
            checkpoint=checkpoint,
            status=_conversation_status(state.task.status),
            previous_resolution_status=checkpoint.previous_resolution_status,
        )

    def fail(self, lease: ConversationLease) -> ConversationThread:
        return self._repository.fail_run(lease)

    def get(self, thread_id: str) -> ConversationThreadDetail:
        result = self._repository.get(thread_id)
        if result is None:
            raise ConversationNotFoundError("conversation was not found")
        return result

    def list(self, *, limit: int = 50) -> list[ConversationThread]:
        return self._repository.list(limit=limit)


__all__ = ["ConversationPersistenceService", "RECENT_TURN_LIMIT"]
