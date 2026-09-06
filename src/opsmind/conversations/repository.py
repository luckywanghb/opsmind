"""Backend-neutral conversation repository contract and errors."""

from __future__ import annotations

from typing import Protocol

from opsmind.conversations.models import (
    ConversationCheckpoint,
    ConversationLease,
    ConversationStatus,
    ConversationThread,
    ConversationThreadDetail,
)
from opsmind.state import ResolutionStatus


class ConversationPersistenceError(RuntimeError):
    code = "CONVERSATION_PERSISTENCE_UNAVAILABLE"


class ConversationNotFoundError(ConversationPersistenceError):
    code = "CONVERSATION_NOT_FOUND"


class ConversationConflictError(ConversationPersistenceError):
    code = "CONVERSATION_CONFLICT"


class ConversationIdentityConflictError(ConversationConflictError):
    code = "CONVERSATION_IDENTITY_CONFLICT"


class ConversationDataIntegrityError(ConversationPersistenceError):
    code = "CONVERSATION_DATA_INTEGRITY_ERROR"


class IncompatibleConversationSchemaError(ConversationPersistenceError):
    code = "CONVERSATION_SCHEMA_INCOMPATIBLE"


class ConversationRepository(Protocol):
    def begin_run(
        self,
        *,
        thread_id: str,
        user_id: str | None,
        message: str,
        request_id: str,
        run_id: str,
        recent_turn_limit: int,
    ) -> ConversationLease: ...

    def complete_run(
        self,
        lease: ConversationLease,
        *,
        assistant_content: str | None,
        checkpoint: ConversationCheckpoint,
        status: ConversationStatus,
        previous_resolution_status: ResolutionStatus,
    ) -> ConversationThread: ...

    def fail_run(self, lease: ConversationLease) -> ConversationThread: ...

    def get(self, thread_id: str) -> ConversationThreadDetail | None: ...

    def list(self, *, limit: int) -> list[ConversationThread]: ...
