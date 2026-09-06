"""Versioned SQLite conversation repository."""

from __future__ import annotations

import sqlite3
import threading
from builtins import list as builtin_list
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

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
    ConversationPersistenceError,
    IncompatibleConversationSchemaError,
)
from opsmind.state import ResolutionStatus

SCHEMA_VERSION = 1
_SCHEMA_INITIALIZATION_LOCK = threading.Lock()
_DOMAIN_TABLES = {
    "conversation_threads",
    "conversation_turns",
    "conversation_checkpoints",
}
_EXPECTED_COLUMNS = {
    "conversation_schema_metadata": {"key", "value"},
    "conversation_threads": {
        "thread_id",
        "user_id",
        "created_at",
        "updated_at",
        "status",
        "original_query",
        "previous_resolution_status",
        "latest_run_id",
        "turn_count",
        "revision",
        "active_run_id",
    },
    "conversation_turns": {
        "turn_id",
        "thread_id",
        "sequence",
        "role",
        "content",
        "request_id",
        "run_id",
        "created_at",
    },
    "conversation_checkpoints": {
        "thread_id",
        "revision",
        "checkpoint_json",
        "updated_at",
    },
}

_CREATE_SCHEMA = """
CREATE TABLE conversation_threads (
    thread_id TEXT PRIMARY KEY NOT NULL,
    user_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('ACTIVE', 'WAITING_USER', 'RESOLVED', 'TRANSFERRED', 'CLOSED')
    ),
    original_query TEXT NOT NULL,
    previous_resolution_status TEXT NOT NULL CHECK (
        previous_resolution_status IN (
            'UNKNOWN', 'UNRESOLVED', 'PARTIALLY_RESOLVED', 'RESOLVED'
        )
    ),
    latest_run_id TEXT NOT NULL,
    turn_count INTEGER NOT NULL CHECK (turn_count >= 0),
    revision INTEGER NOT NULL CHECK (revision >= 0),
    active_run_id TEXT
);
CREATE TABLE conversation_turns (
    turn_id TEXT PRIMARY KEY NOT NULL,
    thread_id TEXT NOT NULL,
    sequence INTEGER NOT NULL CHECK (sequence >= 1),
    role TEXT NOT NULL CHECK (role IN ('USER', 'ASSISTANT')),
    content TEXT NOT NULL,
    request_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (thread_id, sequence),
    FOREIGN KEY (thread_id) REFERENCES conversation_threads(thread_id)
        ON DELETE CASCADE
);
CREATE TABLE conversation_checkpoints (
    thread_id TEXT PRIMARY KEY NOT NULL,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    checkpoint_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (thread_id) REFERENCES conversation_threads(thread_id)
        ON DELETE CASCADE
);
CREATE INDEX idx_conversation_threads_updated
    ON conversation_threads(updated_at);
CREATE INDEX idx_conversation_turns_thread
    ON conversation_turns(thread_id, sequence);
"""


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


class SQLiteConversationRepository:
    """Connection-per-operation store with atomic conversation mutations."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._initialization_lock = threading.Lock()
        self._initialized = False

    @property
    def path(self) -> Path:
        return self._path

    def begin_run(
        self,
        *,
        thread_id: str,
        user_id: str | None,
        message: str,
        request_id: str,
        run_id: str,
        recent_turn_limit: int,
    ) -> ConversationLease:
        if not 0 <= recent_turn_limit <= 6:
            raise ValueError("recent turn limit must be between 0 and 6")
        now = _utc_now()
        try:
            with self._transaction() as connection:
                row = connection.execute(
                    "SELECT * FROM conversation_threads WHERE thread_id = ?",
                    (thread_id,),
                ).fetchone()
                if row is None:
                    connection.execute(
                        """
                        INSERT INTO conversation_threads (
                            thread_id, user_id, created_at, updated_at, status,
                            original_query, previous_resolution_status,
                            latest_run_id, turn_count, revision, active_run_id
                        ) VALUES (?, ?, ?, ?, 'ACTIVE', ?, 'UNKNOWN', ?, 1, 1, ?)
                        """,
                        (
                            thread_id,
                            user_id,
                            _utc_text(now),
                            _utc_text(now),
                            message,
                            run_id,
                            run_id,
                        ),
                    )
                    thread = ConversationThread(
                        thread_id=thread_id,
                        user_id=user_id,
                        created_at=now,
                        updated_at=now,
                        status=ConversationStatus.ACTIVE,
                        original_query=message,
                        previous_resolution_status=ResolutionStatus.UNKNOWN,
                        latest_run_id=run_id,
                        turn_count=1,
                        revision=1,
                        active_run_id=run_id,
                    )
                    checkpoint = None
                    recent_turns: list[ConversationTurn] = []
                    sequence = 1
                else:
                    existing = self._thread(row)
                    if existing.active_run_id is not None:
                        raise ConversationConflictError(
                            "conversation already has an active run"
                        )
                    if (
                        existing.user_id is not None
                        and user_id is not None
                        and existing.user_id != user_id
                    ):
                        raise ConversationIdentityConflictError(
                            "conversation identity does not match"
                        )
                    checkpoint = self._load_checkpoint(connection, thread_id)
                    recent_turns = self._load_recent_turns(
                        connection, thread_id, recent_turn_limit
                    )
                    sequence = existing.turn_count + 1
                    revision = existing.revision + 1
                    bound_user_id = existing.user_id or user_id
                    cursor = connection.execute(
                        """
                        UPDATE conversation_threads
                        SET user_id = ?, updated_at = ?, latest_run_id = ?,
                            turn_count = ?, revision = ?, active_run_id = ?
                        WHERE thread_id = ? AND revision = ?
                          AND active_run_id IS NULL
                        """,
                        (
                            bound_user_id,
                            _utc_text(now),
                            run_id,
                            sequence,
                            revision,
                            run_id,
                            thread_id,
                            existing.revision,
                        ),
                    )
                    if cursor.rowcount != 1:
                        raise ConversationConflictError(
                            "conversation changed while starting run"
                        )
                    thread = existing.model_copy(
                        update={
                            "user_id": bound_user_id,
                            "updated_at": now,
                            "latest_run_id": run_id,
                            "turn_count": sequence,
                            "revision": revision,
                            "active_run_id": run_id,
                        }
                    )
                turn = ConversationTurn(
                    turn_id=str(uuid4()),
                    thread_id=thread_id,
                    sequence=sequence,
                    role=ConversationRole.USER,
                    content=message,
                    request_id=request_id,
                    run_id=run_id,
                    created_at=now,
                )
                self._insert_turn(connection, turn)
                snapshot = ConversationContextSnapshot(
                    thread=thread,
                    checkpoint=checkpoint,
                    recent_turns=recent_turns,
                )
                return ConversationLease(
                    thread_id=thread_id,
                    request_id=request_id,
                    run_id=run_id,
                    revision=thread.revision,
                    user_turn_sequence=sequence,
                    context=snapshot,
                )
        except (ConversationConflictError, ConversationIdentityConflictError):
            raise
        except ConversationPersistenceError:
            raise
        except sqlite3.IntegrityError as exc:
            raise ConversationConflictError(
                "conversation turn conflicts with stored ordering"
            ) from exc
        except (sqlite3.Error, OSError) as exc:
            raise ConversationPersistenceError(
                "conversation start persistence failed"
            ) from exc

    def complete_run(
        self,
        lease: ConversationLease,
        *,
        assistant_content: str | None,
        checkpoint: ConversationCheckpoint,
        status: ConversationStatus,
        previous_resolution_status: ResolutionStatus,
    ) -> ConversationThread:
        canonical_lease = ConversationLease.model_validate(lease)
        canonical_checkpoint = ConversationCheckpoint.model_validate(checkpoint)
        expected_terminal_revision = canonical_lease.revision + 1
        if (
            canonical_checkpoint.thread_id != canonical_lease.thread_id
            or canonical_checkpoint.latest_run_id != canonical_lease.run_id
            or canonical_checkpoint.revision != expected_terminal_revision
        ):
            raise ConversationConflictError("checkpoint does not match active run")
        now = canonical_checkpoint.updated_at
        try:
            with self._transaction() as connection:
                row = connection.execute(
                    "SELECT * FROM conversation_threads WHERE thread_id = ?",
                    (canonical_lease.thread_id,),
                ).fetchone()
                if row is None:
                    raise ConversationConflictError("conversation is missing")
                existing = self._thread(row)
                if (
                    existing.revision != canonical_lease.revision
                    or existing.active_run_id != canonical_lease.run_id
                ):
                    raise ConversationConflictError(
                        "conversation changed before terminal update"
                    )
                sequence = existing.turn_count
                if assistant_content is not None:
                    sequence += 1
                    assistant_turn = ConversationTurn(
                        turn_id=str(uuid4()),
                        thread_id=canonical_lease.thread_id,
                        sequence=sequence,
                        role=ConversationRole.ASSISTANT,
                        content=assistant_content,
                        request_id=canonical_lease.request_id,
                        run_id=canonical_lease.run_id,
                        created_at=now,
                    )
                    self._insert_turn(connection, assistant_turn)
                connection.execute(
                    """
                    INSERT INTO conversation_checkpoints (
                        thread_id, revision, checkpoint_json, updated_at
                    ) VALUES (?, ?, ?, ?)
                    ON CONFLICT(thread_id) DO UPDATE SET
                        revision = excluded.revision,
                        checkpoint_json = excluded.checkpoint_json,
                        updated_at = excluded.updated_at
                    """,
                    (
                        canonical_checkpoint.thread_id,
                        canonical_checkpoint.revision,
                        canonical_checkpoint.model_dump_json(),
                        _utc_text(now),
                    ),
                )
                cursor = connection.execute(
                    """
                    UPDATE conversation_threads
                    SET updated_at = ?, status = ?,
                        previous_resolution_status = ?, turn_count = ?,
                        revision = ?, active_run_id = NULL
                    WHERE thread_id = ? AND revision = ? AND active_run_id = ?
                    """,
                    (
                        _utc_text(now),
                        status.value,
                        previous_resolution_status.value,
                        sequence,
                        expected_terminal_revision,
                        canonical_lease.thread_id,
                        canonical_lease.revision,
                        canonical_lease.run_id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise ConversationConflictError(
                        "conversation terminal revision conflict"
                    )
                return existing.model_copy(
                    update={
                        "updated_at": now,
                        "status": status,
                        "previous_resolution_status": previous_resolution_status,
                        "turn_count": sequence,
                        "revision": expected_terminal_revision,
                        "active_run_id": None,
                    }
                )
        except ConversationConflictError:
            raise
        except ConversationPersistenceError:
            raise
        except sqlite3.IntegrityError as exc:
            raise ConversationConflictError(
                "conversation terminal update conflicts with stored data"
            ) from exc
        except (sqlite3.Error, OSError) as exc:
            raise ConversationPersistenceError(
                "conversation terminal persistence failed"
            ) from exc

    def fail_run(self, lease: ConversationLease) -> ConversationThread:
        canonical = ConversationLease.model_validate(lease)
        now = _utc_now()
        try:
            with self._transaction() as connection:
                row = connection.execute(
                    "SELECT * FROM conversation_threads WHERE thread_id = ?",
                    (canonical.thread_id,),
                ).fetchone()
                if row is None:
                    raise ConversationConflictError("conversation is missing")
                existing = self._thread(row)
                cursor = connection.execute(
                    """
                    UPDATE conversation_threads
                    SET updated_at = ?, revision = revision + 1,
                        active_run_id = NULL
                    WHERE thread_id = ? AND revision = ? AND active_run_id = ?
                    """,
                    (
                        _utc_text(now),
                        canonical.thread_id,
                        canonical.revision,
                        canonical.run_id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise ConversationConflictError(
                        "conversation changed before failed-run release"
                    )
                return existing.model_copy(
                    update={
                        "updated_at": now,
                        "revision": existing.revision + 1,
                        "active_run_id": None,
                    }
                )
        except ConversationConflictError:
            raise
        except ConversationPersistenceError:
            raise
        except (sqlite3.Error, OSError) as exc:
            raise ConversationPersistenceError(
                "failed conversation run could not be released"
            ) from exc

    def get(self, thread_id: str) -> ConversationThreadDetail | None:
        try:
            connection = self._connect()
            try:
                connection.execute("BEGIN")
                row = connection.execute(
                    "SELECT * FROM conversation_threads WHERE thread_id = ?",
                    (thread_id,),
                ).fetchone()
                if row is None:
                    connection.commit()
                    return None
                turn_rows = connection.execute(
                    """SELECT * FROM conversation_turns
                       WHERE thread_id = ? ORDER BY sequence ASC""",
                    (thread_id,),
                ).fetchall()
                checkpoint = self._load_checkpoint(connection, thread_id)
                connection.commit()
            finally:
                if connection.in_transaction:
                    connection.rollback()
                connection.close()
            return ConversationThreadDetail(
                thread=self._thread(row),
                turns=[self._turn(item) for item in turn_rows],
                checkpoint=checkpoint,
            )
        except ConversationPersistenceError:
            raise
        except (sqlite3.Error, ValidationError, ValueError, TypeError) as exc:
            raise ConversationDataIntegrityError(
                "stored conversation failed typed validation"
            ) from exc

    def list(self, *, limit: int) -> list[ConversationThread]:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        try:
            connection = self._connect()
            try:
                rows = connection.execute(
                    """SELECT * FROM conversation_threads
                       ORDER BY updated_at DESC, thread_id DESC LIMIT ?""",
                    (limit,),
                ).fetchall()
            finally:
                connection.close()
            return [self._thread(row) for row in rows]
        except ConversationPersistenceError:
            raise
        except (sqlite3.Error, ValidationError, ValueError, TypeError) as exc:
            raise ConversationDataIntegrityError(
                "stored conversation list failed typed validation"
            ) from exc

    def _load_checkpoint(
        self, connection: sqlite3.Connection, thread_id: str
    ) -> ConversationCheckpoint | None:
        row = connection.execute(
            "SELECT checkpoint_json FROM conversation_checkpoints WHERE thread_id = ?",
            (thread_id,),
        ).fetchone()
        if row is None:
            return None
        return ConversationCheckpoint.model_validate_json(row["checkpoint_json"])

    def _load_recent_turns(
        self, connection: sqlite3.Connection, thread_id: str, limit: int
    ) -> builtin_list[ConversationTurn]:
        if limit == 0:
            return []
        rows = connection.execute(
            """SELECT * FROM (
                   SELECT * FROM conversation_turns
                   WHERE thread_id = ? ORDER BY sequence DESC LIMIT ?
               ) ORDER BY sequence ASC""",
            (thread_id, limit),
        ).fetchall()
        return [self._turn(row) for row in rows]

    @staticmethod
    def _insert_turn(
        connection: sqlite3.Connection, turn: ConversationTurn
    ) -> None:
        connection.execute(
            """INSERT INTO conversation_turns (
                   turn_id, thread_id, sequence, role, content,
                   request_id, run_id, created_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                turn.turn_id,
                turn.thread_id,
                turn.sequence,
                turn.role.value,
                turn.content,
                turn.request_id,
                turn.run_id,
                _utc_text(turn.created_at),
            ),
        )

    @staticmethod
    def _thread(row: sqlite3.Row) -> ConversationThread:
        return ConversationThread(
            thread_id=row["thread_id"],
            user_id=row["user_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            status=row["status"],
            original_query=row["original_query"],
            previous_resolution_status=row["previous_resolution_status"],
            latest_run_id=row["latest_run_id"],
            turn_count=row["turn_count"],
            revision=row["revision"],
            active_run_id=row["active_run_id"],
        )

    @staticmethod
    def _turn(row: sqlite3.Row) -> ConversationTurn:
        return ConversationTurn(
            turn_id=row["turn_id"],
            thread_id=row["thread_id"],
            sequence=row["sequence"],
            role=row["role"],
            content=row["content"],
            request_id=row["request_id"],
            run_id=row["run_id"],
            created_at=row["created_at"],
        )

    def _connect(self) -> sqlite3.Connection:
        self._ensure_initialized()
        return self._new_connection()

    def _new_connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        with self._initialization_lock, _SCHEMA_INITIALIZATION_LOCK:
            if self._initialized:
                return
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                connection = self._new_connection()
                try:
                    connection.execute("PRAGMA journal_mode = WAL")
                    connection.execute("BEGIN IMMEDIATE")
                    connection.execute(
                        """CREATE TABLE IF NOT EXISTS conversation_schema_metadata (
                               key TEXT PRIMARY KEY NOT NULL,
                               value TEXT NOT NULL
                           )"""
                    )
                    row = connection.execute(
                        """SELECT value FROM conversation_schema_metadata
                           WHERE key = 'schema_version'"""
                    ).fetchone()
                    if row is None:
                        existing = self._table_names(connection)
                        if existing.intersection(_DOMAIN_TABLES):
                            raise IncompatibleConversationSchemaError(
                                "conversation schema has no version metadata"
                            )
                        for statement in _CREATE_SCHEMA.split(";"):
                            if statement.strip():
                                connection.execute(statement)
                        connection.execute(
                            """INSERT INTO conversation_schema_metadata
                               (key, value) VALUES ('schema_version', ?)""",
                            (str(SCHEMA_VERSION),),
                        )
                    else:
                        try:
                            version = int(row["value"])
                        except (TypeError, ValueError) as exc:
                            raise IncompatibleConversationSchemaError(
                                "conversation schema version is invalid"
                            ) from exc
                        if version != SCHEMA_VERSION:
                            raise IncompatibleConversationSchemaError(
                                "conversation schema version is incompatible"
                            )
                        self._validate_schema(connection)
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
                finally:
                    connection.close()
            except ConversationPersistenceError:
                raise
            except (sqlite3.Error, OSError) as exc:
                raise ConversationPersistenceError(
                    "conversation schema initialization failed"
                ) from exc
            self._initialized = True

    def _validate_schema(self, connection: sqlite3.Connection) -> None:
        tables = self._table_names(connection)
        if not set(_EXPECTED_COLUMNS).issubset(tables):
            raise IncompatibleConversationSchemaError(
                "conversation schema tables are incomplete"
            )
        for table, expected in _EXPECTED_COLUMNS.items():
            columns = {
                str(row["name"])
                for row in connection.execute(f"PRAGMA table_info({table})")
            }
            if columns != expected:
                raise IncompatibleConversationSchemaError(
                    f"conversation schema table {table} is incompatible"
                )

    @staticmethod
    def _table_names(connection: sqlite3.Connection) -> set[str]:
        return {
            str(row["name"])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }


__all__ = ["SCHEMA_VERSION", "SQLiteConversationRepository"]
