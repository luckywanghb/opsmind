"""Conversation persistence public boundary."""

from opsmind.conversations.models import (
    ConversationCheckpoint,
    ConversationContextSnapshot,
    ConversationLease,
    ConversationRole,
    ConversationStatus,
    ConversationThread,
    ConversationThreadDetail,
    ConversationTurn,
)
from opsmind.conversations.repository import (
    ConversationConflictError,
    ConversationDataIntegrityError,
    ConversationIdentityConflictError,
    ConversationNotFoundError,
    ConversationPersistenceError,
    ConversationRepository,
    IncompatibleConversationSchemaError,
)
from opsmind.conversations.service import ConversationPersistenceService
from opsmind.conversations.sqlite import SCHEMA_VERSION, SQLiteConversationRepository

__all__ = [
    "ConversationCheckpoint",
    "ConversationConflictError",
    "ConversationContextSnapshot",
    "ConversationDataIntegrityError",
    "ConversationIdentityConflictError",
    "ConversationLease",
    "ConversationNotFoundError",
    "ConversationPersistenceError",
    "ConversationPersistenceService",
    "ConversationRepository",
    "ConversationRole",
    "ConversationStatus",
    "ConversationThread",
    "ConversationThreadDetail",
    "ConversationTurn",
    "IncompatibleConversationSchemaError",
    "SCHEMA_VERSION",
    "SQLiteConversationRepository",
]
