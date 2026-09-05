"""Local SQLite implementation of the Agent-run repository contract."""

from __future__ import annotations

import sqlite3
import threading
from builtins import list as builtin_list
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from pydantic import BaseModel, ValidationError

from opsmind.models import ModelProfile
from opsmind.runs.models import (
    AgentRun,
    AgentRunSummary,
    RunLifecycleStatus,
    RunStep,
    RuntimeMetadata,
    SafeSourceContext,
)
from opsmind.runs.repository import (
    IncompatibleRunSchemaError,
    RunAlreadyExistsError,
    RunDataIntegrityError,
    RunPersistenceError,
    RunStateConflictError,
)
from opsmind.state import DecisionState, EvidenceItem, HandoffState, UnderstandingState

SCHEMA_VERSION = 1
_DOMAIN_TABLES = frozenset({"agent_runs", "run_steps", "evidence_records"})
_REQUIRED_INDEXES: Final = {
    "idx_agent_runs_thread_id": ("agent_runs", ("thread_id",)),
    "idx_agent_runs_started_at": ("agent_runs", ("started_at",)),
    "idx_agent_runs_lifecycle_status": ("agent_runs", ("lifecycle_status",)),
}

_CREATE_SCHEMA = """
CREATE TABLE agent_runs (
    run_id TEXT PRIMARY KEY NOT NULL,
    request_id TEXT NOT NULL UNIQUE,
    thread_id TEXT NOT NULL,
    lifecycle_status TEXT NOT NULL CHECK (
        lifecycle_status IN ('STARTED', 'SUCCEEDED', 'FAILED')
    ),
    agent_terminal_status TEXT,
    input_message TEXT NOT NULL,
    source_context_json TEXT NOT NULL,
    understanding_json TEXT,
    decision_json TEXT,
    final_reply TEXT,
    handoff_json TEXT,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    duration_ms REAL,
    error_code TEXT,
    runtime_metadata_json TEXT NOT NULL
);
CREATE TABLE run_steps (
    run_id TEXT NOT NULL,
    sequence INTEGER NOT NULL CHECK (sequence >= 0),
    node TEXT NOT NULL,
    task TEXT NOT NULL,
    profile TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('completed', 'failed', 'blocked')),
    summary TEXT NOT NULL,
    PRIMARY KEY (run_id, sequence),
    FOREIGN KEY (run_id) REFERENCES agent_runs(run_id) ON DELETE CASCADE
);
CREATE TABLE evidence_records (
    run_id TEXT NOT NULL,
    sequence INTEGER NOT NULL CHECK (sequence >= 0),
    evidence_id TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    PRIMARY KEY (run_id, sequence),
    UNIQUE (run_id, evidence_id),
    FOREIGN KEY (run_id) REFERENCES agent_runs(run_id) ON DELETE CASCADE
);
CREATE INDEX idx_agent_runs_thread_id ON agent_runs(thread_id);
CREATE INDEX idx_agent_runs_started_at ON agent_runs(started_at);
CREATE INDEX idx_agent_runs_lifecycle_status ON agent_runs(lifecycle_status);
"""

_EXPECTED_COLUMNS = {
    "schema_metadata": {"key", "value"},
    "agent_runs": {
        "run_id",
        "request_id",
        "thread_id",
        "lifecycle_status",
        "agent_terminal_status",
        "input_message",
        "source_context_json",
        "understanding_json",
        "decision_json",
        "final_reply",
        "handoff_json",
        "started_at",
        "completed_at",
        "duration_ms",
        "error_code",
        "runtime_metadata_json",
    },
    "run_steps": {"run_id", "sequence", "node", "task", "profile", "status", "summary"},
    "evidence_records": {"run_id", "sequence", "evidence_id", "evidence_json"},
}


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _json(model: BaseModel) -> str:
    return model.model_dump_json()


class SQLiteRunRepository:
    """Connection-per-operation local store with transactional finalization."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._initialization_lock = threading.Lock()
        self._initialized = False

    @property
    def path(self) -> Path:
        return self._path

    def create_started(self, run: AgentRun) -> None:
        canonical = AgentRun.model_validate(run)
        if canonical.lifecycle_status is not RunLifecycleStatus.STARTED:
            raise RunStateConflictError("create requires STARTED lifecycle")
        try:
            with self._transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO agent_runs (
                        run_id, request_id, thread_id, lifecycle_status,
                        agent_terminal_status, input_message, source_context_json,
                        understanding_json, decision_json, final_reply, handoff_json,
                        started_at, completed_at, duration_ms, error_code,
                        runtime_metadata_json
                    ) VALUES (?, ?, ?, ?, NULL, ?, ?, NULL, NULL, NULL, NULL, ?,
                              NULL, NULL, NULL, ?)
                    """,
                    (
                        canonical.run_id,
                        canonical.request_id,
                        canonical.thread_id,
                        canonical.lifecycle_status.value,
                        canonical.input_message,
                        _json(canonical.source_context),
                        _utc_text(canonical.started_at),
                        _json(canonical.runtime_metadata),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise RunAlreadyExistsError(
                "run or request identifier already exists"
            ) from exc
        except RunPersistenceError:
            raise
        except sqlite3.Error as exc:
            raise RunPersistenceError("run start persistence failed") from exc

    def finalize_succeeded(self, *, run: AgentRun) -> None:
        canonical = AgentRun.model_validate(run)
        if canonical.lifecycle_status is not RunLifecycleStatus.SUCCEEDED:
            raise RunStateConflictError("success finalization requires SUCCEEDED")
        self._finalize(canonical)

    def finalize_failed(self, *, run: AgentRun) -> None:
        canonical = AgentRun.model_validate(run)
        if canonical.lifecycle_status is not RunLifecycleStatus.FAILED:
            raise RunStateConflictError("failure finalization requires FAILED")
        self._finalize(canonical)

    def get(self, run_id: str) -> AgentRun | None:
        try:
            connection = self._connect()
            try:
                # Keep all projections in one SQLite read snapshot.  WAL mode
                # (enabled during initialization) allows a terminal writer to
                # commit while this consistent snapshot is being consumed.
                connection.execute("BEGIN")
                row = connection.execute(
                    "SELECT * FROM agent_runs WHERE run_id = ?", (run_id,)
                ).fetchone()
                if row is None:
                    connection.commit()
                    return None
                step_rows = connection.execute(
                    """SELECT sequence, node, task, profile, status, summary
                       FROM run_steps WHERE run_id = ? ORDER BY sequence ASC""",
                    (run_id,),
                ).fetchall()
                evidence_rows = connection.execute(
                    """SELECT sequence, evidence_id, evidence_json
                       FROM evidence_records
                       WHERE run_id = ? ORDER BY sequence ASC""",
                    (run_id,),
                ).fetchall()
                connection.commit()
            finally:
                if connection.in_transaction:
                    connection.rollback()
                connection.close()
            return self._detail(row, step_rows, evidence_rows)
        except RunPersistenceError:
            raise
        except (sqlite3.Error, ValidationError, ValueError, TypeError) as exc:
            raise RunDataIntegrityError("stored run failed typed validation") from exc

    def list(self, *, limit: int) -> list[AgentRunSummary]:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        try:
            connection = self._connect()
            try:
                rows = connection.execute(
                    """
                    SELECT run_id, request_id, thread_id, lifecycle_status,
                           agent_terminal_status, started_at, completed_at,
                           duration_ms, error_code
                    FROM agent_runs
                    ORDER BY started_at DESC, run_id DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            finally:
                connection.close()
            return [self._summary(row) for row in rows]
        except RunPersistenceError:
            raise
        except (sqlite3.Error, ValidationError, ValueError, TypeError) as exc:
            raise RunDataIntegrityError(
                "stored run list failed typed validation"
            ) from exc

    def _finalize(self, run: AgentRun) -> None:
        assert run.completed_at is not None
        assert run.duration_ms is not None
        try:
            with self._transaction() as connection:
                cursor = connection.execute(
                    """
                    UPDATE agent_runs
                    SET lifecycle_status = ?, agent_terminal_status = ?,
                        understanding_json = ?, decision_json = ?, final_reply = ?,
                        handoff_json = ?, completed_at = ?, duration_ms = ?,
                        error_code = ?, runtime_metadata_json = ?
                    WHERE run_id = ? AND lifecycle_status = 'STARTED'
                    """,
                    (
                        run.lifecycle_status.value,
                        run.agent_terminal_status,
                        _json(run.understanding) if run.understanding else None,
                        _json(run.decision) if run.decision else None,
                        run.final_reply,
                        _json(run.handoff) if run.handoff else None,
                        _utc_text(run.completed_at),
                        run.duration_ms,
                        run.error_code,
                        _json(run.runtime_metadata),
                        run.run_id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise RunStateConflictError("run is missing or already terminal")
                connection.executemany(
                    """INSERT INTO run_steps
                       (run_id, sequence, node, task, profile, status, summary)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    [
                        (
                            run.run_id,
                            step.sequence,
                            step.node,
                            step.task.value,
                            (
                                step.profile.value
                                if isinstance(step.profile, ModelProfile)
                                else step.profile
                            ),
                            step.status,
                            step.summary,
                        )
                        for step in run.steps
                    ],
                )
                connection.executemany(
                    """INSERT INTO evidence_records
                       (run_id, sequence, evidence_id, evidence_json)
                       VALUES (?, ?, ?, ?)""",
                    [
                        (run.run_id, sequence, item.evidence_id, _json(item))
                        for sequence, item in enumerate(run.evidence)
                    ],
                )
        except RunPersistenceError:
            raise
        except sqlite3.Error as exc:
            raise RunPersistenceError("run finalization persistence failed") from exc

    def _connect(self) -> sqlite3.Connection:
        self._ensure_initialized()
        return self._new_connection()

    def _new_connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        with self._initialization_lock:
            if self._initialized:
                return
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                connection = self._new_connection()
                try:
                    connection.execute("PRAGMA journal_mode = WAL")
                    connection.execute("BEGIN IMMEDIATE")
                    connection.execute(
                        """CREATE TABLE IF NOT EXISTS schema_metadata (
                               key TEXT PRIMARY KEY NOT NULL,
                               value TEXT NOT NULL
                           )"""
                    )
                    row = connection.execute(
                        "SELECT value FROM schema_metadata WHERE key = 'schema_version'"
                    ).fetchone()
                    if row is None:
                        existing = self._table_names(connection)
                        if existing.intersection(_DOMAIN_TABLES):
                            raise IncompatibleRunSchemaError(
                                "run schema has no version metadata"
                            )
                        for statement in _CREATE_SCHEMA.split(";"):
                            if statement.strip():
                                connection.execute(statement)
                        connection.execute(
                            "INSERT INTO schema_metadata (key, value) VALUES (?, ?)",
                            ("schema_version", str(SCHEMA_VERSION)),
                        )
                    else:
                        try:
                            version = int(row["value"])
                        except (TypeError, ValueError) as exc:
                            raise IncompatibleRunSchemaError(
                                "run schema version is invalid"
                            ) from exc
                        if version != SCHEMA_VERSION:
                            raise IncompatibleRunSchemaError(
                                "run schema version is incompatible"
                            )
                        self._validate_schema(connection)
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
                finally:
                    connection.close()
            except RunPersistenceError:
                raise
            except (OSError, sqlite3.Error) as exc:
                raise RunPersistenceError("run schema initialization failed") from exc
            self._initialized = True

    def _validate_schema(self, connection: sqlite3.Connection) -> None:
        table_names = self._table_names(connection)
        if not set(_EXPECTED_COLUMNS).issubset(table_names):
            raise IncompatibleRunSchemaError("run schema tables are incomplete")
        for table, expected in _EXPECTED_COLUMNS.items():
            column_rows = list(
                connection.execute(f"PRAGMA table_info({table})")
            )
            columns = {str(row["name"]) for row in column_rows}
            if columns != expected:
                raise IncompatibleRunSchemaError(
                    f"run schema table {table} is incompatible"
                )
            self._validate_columns(table, column_rows)
            self._validate_table_checks(connection, table)

        self._validate_primary_keys(connection)
        self._validate_unique_constraints(connection)
        self._validate_foreign_keys(connection)
        self._validate_indexes(connection)

    @staticmethod
    def _validate_columns(table: str, rows: builtin_list[sqlite3.Row]) -> None:
        required_not_null = {
            "schema_metadata": {"key", "value"},
            "agent_runs": {
                "run_id",
                "request_id",
                "thread_id",
                "lifecycle_status",
                "input_message",
                "source_context_json",
                "started_at",
                "runtime_metadata_json",
            },
            "run_steps": {
                "run_id",
                "sequence",
                "node",
                "task",
                "profile",
                "status",
                "summary",
            },
            "evidence_records": {
                "run_id",
                "sequence",
                "evidence_id",
                "evidence_json",
            },
        }[table]
        for row in rows:
            if bool(row["notnull"]) != (str(row["name"]) in required_not_null):
                raise IncompatibleRunSchemaError(
                    f"run schema table {table} has incompatible nullability"
                )

    @staticmethod
    def _validate_table_checks(
        connection: sqlite3.Connection,
        table: str,
    ) -> None:
        row = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        sql = "" if row is None or row["sql"] is None else str(row["sql"])
        normalized = "".join(sql.upper().split())
        required_fragments = {
            "agent_runs": (
                "CHECK(LIFECYCLE_STATUSIN('STARTED','SUCCEEDED','FAILED'))",
            ),
            "run_steps": (
                "CHECK(SEQUENCE>=0)",
                "CHECK(STATUSIN('COMPLETED','FAILED','BLOCKED'))",
            ),
            "evidence_records": ("CHECK(SEQUENCE>=0)",),
            "schema_metadata": (),
        }[table]
        if any(fragment not in normalized for fragment in required_fragments):
            raise IncompatibleRunSchemaError(
                f"run schema table {table} is missing required checks"
            )

    @staticmethod
    def _validate_primary_keys(connection: sqlite3.Connection) -> None:
        expected = {
            "schema_metadata": ("key",),
            "agent_runs": ("run_id",),
            "run_steps": ("run_id", "sequence"),
            "evidence_records": ("run_id", "sequence"),
        }
        for table, columns in expected.items():
            rows = sorted(
                connection.execute(f"PRAGMA table_info({table})").fetchall(),
                key=lambda row: int(row["pk"]),
            )
            actual = tuple(str(row["name"]) for row in rows if row["pk"])
            if actual != columns:
                raise IncompatibleRunSchemaError(
                    f"run schema table {table} has incompatible primary key"
                )

    @staticmethod
    def _validate_unique_constraints(connection: sqlite3.Connection) -> None:
        expected = {
            "agent_runs": (("request_id",),),
            "evidence_records": (("run_id", "evidence_id"),),
        }
        for table, constraints in expected.items():
            indexes = SQLiteRunRepository._index_definitions(connection, table)
            for columns in constraints:
                if not any(
                    unique and index_columns == columns
                    for _, unique, index_columns in indexes
                ):
                    raise IncompatibleRunSchemaError(
                        f"run schema table {table} is missing required uniqueness"
                    )

    @staticmethod
    def _validate_foreign_keys(connection: sqlite3.Connection) -> None:
        for table in ("run_steps", "evidence_records"):
            rows = connection.execute(f"PRAGMA foreign_key_list({table})").fetchall()
            if not any(
                row["table"] == "agent_runs"
                and row["from"] == "run_id"
                and row["to"] == "run_id"
                and str(row["on_delete"]).upper() == "CASCADE"
                for row in rows
            ):
                raise IncompatibleRunSchemaError(
                    f"run schema table {table} is missing required foreign key"
                )

    @staticmethod
    def _index_definitions(
        connection: sqlite3.Connection,
        table: str,
    ) -> builtin_list[tuple[str, bool, tuple[str, ...]]]:
        definitions: builtin_list[tuple[str, bool, tuple[str, ...]]] = []
        for row in connection.execute(f"PRAGMA index_list({table})"):
            index_name = str(row["name"])
            columns = tuple(
                str(info["name"])
                for info in sorted(
                    connection.execute(f"PRAGMA index_info({index_name})").fetchall(),
                    key=lambda info: int(info["seqno"]),
                )
            )
            definitions.append((index_name, bool(row["unique"]), columns))
        return definitions

    @staticmethod
    def _validate_indexes(connection: sqlite3.Connection) -> None:
        definitions = SQLiteRunRepository._index_definitions
        for name, (table, columns) in _REQUIRED_INDEXES.items():
            if not any(
                index_name == name
                and not unique
                and index_columns == columns
                for index_name, unique, index_columns in definitions(connection, table)
            ):
                raise IncompatibleRunSchemaError(
                    f"run schema is missing required index {name}"
                )

    @staticmethod
    def _table_names(connection: sqlite3.Connection) -> set[str]:
        return {
            str(row["name"])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }

    class _Transaction:
        def __init__(self, repository: SQLiteRunRepository) -> None:
            self._repository = repository
            self.connection: sqlite3.Connection | None = None

        def __enter__(self) -> sqlite3.Connection:
            self.connection = self._repository._connect()
            self.connection.execute("BEGIN IMMEDIATE")
            return self.connection

        def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
            assert self.connection is not None
            try:
                if exc_type is None:
                    self.connection.commit()
                else:
                    self.connection.rollback()
            finally:
                self.connection.close()

    def _transaction(self) -> SQLiteRunRepository._Transaction:
        return self._Transaction(self)

    @staticmethod
    def _summary(row: sqlite3.Row) -> AgentRunSummary:
        return AgentRunSummary(
            run_id=row["run_id"],
            request_id=row["request_id"],
            thread_id=row["thread_id"],
            lifecycle_status=row["lifecycle_status"],
            agent_terminal_status=row["agent_terminal_status"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            duration_ms=row["duration_ms"],
            error_code=row["error_code"],
        )

    @classmethod
    def _detail(
        cls,
        row: sqlite3.Row,
        step_rows: Iterable[sqlite3.Row],
        evidence_rows: Iterable[sqlite3.Row],
    ) -> AgentRun:
        summary = cls._summary(row)
        evidence_rows = list(evidence_rows)
        evidence_items = [
            EvidenceItem.model_validate_json(item["evidence_json"])
            for item in evidence_rows
        ]
        if [item["sequence"] for item in evidence_rows] != list(
            range(len(evidence_rows))
        ):
            raise RunDataIntegrityError("stored evidence ordering is invalid")
        if any(
            row_item["evidence_id"] != evidence.evidence_id
            for row_item, evidence in zip(
                evidence_rows, evidence_items, strict=True
            )
        ):
            raise RunDataIntegrityError("stored evidence identity is inconsistent")
        return AgentRun(
            **summary.model_dump(),
            input_message=row["input_message"],
            source_context=SafeSourceContext.model_validate_json(
                row["source_context_json"]
            ),
            understanding=(
                UnderstandingState.model_validate_json(row["understanding_json"])
                if row["understanding_json"] is not None
                else None
            ),
            decision=(
                DecisionState.model_validate_json(row["decision_json"])
                if row["decision_json"] is not None
                else None
            ),
            final_reply=row["final_reply"],
            handoff=(
                HandoffState.model_validate_json(row["handoff_json"])
                if row["handoff_json"] is not None
                else None
            ),
            runtime_metadata=RuntimeMetadata.model_validate_json(
                row["runtime_metadata_json"]
            ),
            steps=[
                RunStep(
                    sequence=step["sequence"],
                    node=step["node"],
                    task=step["task"],
                    profile=step["profile"],
                    status=step["status"],
                    summary=step["summary"],
                )
                for step in step_rows
            ],
            evidence=evidence_items,
        )


__all__ = ["SCHEMA_VERSION", "SQLiteRunRepository"]
