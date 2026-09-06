"""Independent SQLite persistence for eval jobs on the existing run store."""

from __future__ import annotations

import json
import sqlite3
import threading
from builtins import list as builtin_list
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from pydantic import BaseModel, ValidationError

from opsmind.evals.models import (
    EvalAssertionResult,
    EvalCaseResult,
    EvalCaseRun,
    EvalCaseStatus,
    EvalJob,
    EvalJobLifecycleStatus,
    EvalJobSummary,
)
from opsmind.evals.repository import (
    EvalDataIntegrityError,
    EvalPersistenceError,
    EvalStateConflictError,
    IncompatibleEvalSchemaError,
)

EVAL_SCHEMA_VERSION = 1
_EVAL_DOMAIN_TABLES = frozenset(
    {
        "eval_schema_metadata",
        "eval_jobs",
        "eval_case_results",
        "eval_case_runs",
        "eval_assertion_results",
    }
)
_INITIALIZATION_LOCK = threading.Lock()
_EXPECTED_COLUMNS: Final = {
    "eval_schema_metadata": {"key", "value"},
    "eval_jobs": {
        "eval_job_id",
        "suite_id",
        "suite_version",
        "lifecycle_status",
        "case_count",
        "passed_count",
        "failed_count",
        "error_count",
        "started_at",
        "completed_at",
        "duration_ms",
        "app_version",
        "build_sha",
        "runtime_identity",
        "error_code",
    },
    "eval_case_results": {
        "eval_job_id",
        "case_id",
        "title",
        "status",
        "known_gap",
        "run_ids_json",
        "started_at",
        "completed_at",
        "duration_ms",
        "error_code",
    },
    "eval_case_runs": {"eval_job_id", "case_id", "turn_index", "run_id"},
    "eval_assertion_results": {
        "eval_job_id",
        "case_id",
        "assertion_id",
        "type",
        "blocking",
        "status",
        "expected_safe_json",
        "actual_safe_json",
        "message",
    },
}
_REQUIRED_NOT_NULL: Final = {
    "eval_schema_metadata": {"key", "value"},
    "eval_jobs": {
        "eval_job_id",
        "suite_id",
        "suite_version",
        "lifecycle_status",
        "case_count",
        "passed_count",
        "failed_count",
        "error_count",
        "started_at",
        "app_version",
        "runtime_identity",
    },
    "eval_case_results": {
        "eval_job_id",
        "case_id",
        "title",
        "status",
        "run_ids_json",
        "started_at",
    },
    "eval_case_runs": {"eval_job_id", "case_id", "turn_index", "run_id"},
    "eval_assertion_results": {
        "eval_job_id",
        "case_id",
        "assertion_id",
        "type",
        "blocking",
        "status",
        "message",
    },
}
_EXPECTED_PRIMARY_KEYS: Final = {
    "eval_schema_metadata": ("key",),
    "eval_jobs": ("eval_job_id",),
    "eval_case_results": ("eval_job_id", "case_id"),
    "eval_case_runs": ("eval_job_id", "case_id", "turn_index"),
    "eval_assertion_results": ("eval_job_id", "case_id", "assertion_id"),
}
_EXPECTED_FOREIGN_KEYS: Final = {
    "eval_schema_metadata": (),
    "eval_jobs": (),
    "eval_case_results": (
        ("eval_jobs", ("eval_job_id",), ("eval_job_id",), "CASCADE"),
    ),
    "eval_case_runs": (
        (
            "eval_case_results",
            ("eval_job_id", "case_id"),
            ("eval_job_id", "case_id"),
            "CASCADE",
        ),
    ),
    "eval_assertion_results": (
        (
            "eval_case_results",
            ("eval_job_id", "case_id"),
            ("eval_job_id", "case_id"),
            "CASCADE",
        ),
    ),
}
_EXPECTED_INDEXES: Final = {
    "idx_eval_jobs_started_at": ("eval_jobs", ("started_at",), False),
    "idx_eval_jobs_suite": (
        "eval_jobs",
        ("suite_id", "suite_version"),
        False,
    ),
}

_CREATE_SCHEMA = """
CREATE TABLE IF NOT EXISTS eval_schema_metadata (
    key TEXT PRIMARY KEY NOT NULL,
    value TEXT NOT NULL
);
CREATE TABLE eval_jobs (
    eval_job_id TEXT PRIMARY KEY NOT NULL,
    suite_id TEXT NOT NULL,
    suite_version TEXT NOT NULL,
    lifecycle_status TEXT NOT NULL CHECK (
        lifecycle_status IN ('STARTED', 'COMPLETED', 'FAILED')
    ),
    case_count INTEGER NOT NULL CHECK (case_count >= 0),
    passed_count INTEGER NOT NULL CHECK (passed_count >= 0),
    failed_count INTEGER NOT NULL CHECK (failed_count >= 0),
    error_count INTEGER NOT NULL CHECK (error_count >= 0),
    started_at TEXT NOT NULL,
    completed_at TEXT,
    duration_ms REAL,
    app_version TEXT NOT NULL,
    build_sha TEXT,
    runtime_identity TEXT NOT NULL,
    error_code TEXT
);
CREATE TABLE eval_case_results (
    eval_job_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('PASS', 'FAIL', 'ERROR')),
    known_gap TEXT,
    run_ids_json TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    duration_ms REAL,
    error_code TEXT,
    PRIMARY KEY (eval_job_id, case_id),
    FOREIGN KEY (eval_job_id) REFERENCES eval_jobs(eval_job_id) ON DELETE CASCADE
);
CREATE TABLE eval_case_runs (
    eval_job_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    turn_index INTEGER NOT NULL CHECK (turn_index >= 0),
    run_id TEXT NOT NULL,
    PRIMARY KEY (eval_job_id, case_id, turn_index),
    FOREIGN KEY (eval_job_id, case_id)
      REFERENCES eval_case_results(eval_job_id, case_id) ON DELETE CASCADE
);
CREATE TABLE eval_assertion_results (
    eval_job_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    assertion_id TEXT NOT NULL,
    type TEXT NOT NULL,
    blocking INTEGER NOT NULL CHECK (blocking IN (0, 1)),
    status TEXT NOT NULL CHECK (status IN ('PASS', 'FAIL', 'ERROR')),
    expected_safe_json TEXT,
    actual_safe_json TEXT,
    message TEXT NOT NULL,
    PRIMARY KEY (eval_job_id, case_id, assertion_id),
    FOREIGN KEY (eval_job_id, case_id)
      REFERENCES eval_case_results(eval_job_id, case_id) ON DELETE CASCADE
);
CREATE INDEX idx_eval_jobs_started_at ON eval_jobs(started_at);
CREATE INDEX idx_eval_jobs_suite ON eval_jobs(suite_id, suite_version);
"""


def _utc_text(value: datetime) -> str:
    return (
        value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    )


def _parse_datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("stored eval timestamp is not text")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _json(model: BaseModel) -> str:
    return model.model_dump_json()


class SQLiteEvalRepository:
    """Connection-per-operation repository with atomic eval finalization."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._initialization_lock = threading.Lock()
        self._initialized = False

    @property
    def path(self) -> Path:
        return self._path

    def create_started(self, job: EvalJob) -> None:
        canonical = EvalJob.model_validate(job)
        if canonical.lifecycle_status is not EvalJobLifecycleStatus.STARTED:
            raise EvalStateConflictError("eval create requires STARTED lifecycle")
        try:
            with self._transaction() as connection:
                connection.execute(
                    """INSERT INTO eval_jobs (
                           eval_job_id, suite_id, suite_version, lifecycle_status,
                           case_count, passed_count, failed_count, error_count,
                           started_at, completed_at, duration_ms, app_version,
                           build_sha, runtime_identity, error_code
                       ) VALUES (?, ?, ?, ?, ?, 0, 0, 0, ?, NULL, NULL,
                                  ?, ?, ?, NULL)""",
                    (
                        canonical.eval_job_id,
                        canonical.suite_id,
                        canonical.suite_version,
                        canonical.lifecycle_status.value,
                        canonical.case_count,
                        _utc_text(canonical.started_at),
                        canonical.app_version,
                        canonical.build_sha,
                        canonical.runtime_identity,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise EvalPersistenceError("eval job already exists") from exc
        except EvalPersistenceError:
            raise
        except sqlite3.Error as exc:
            raise EvalPersistenceError("eval job start persistence failed") from exc

    def finalize_completed(self, *, job: EvalJob) -> None:
        canonical = EvalJob.model_validate(job)
        if canonical.lifecycle_status is not EvalJobLifecycleStatus.COMPLETED:
            raise EvalStateConflictError("eval success requires COMPLETED lifecycle")
        assert canonical.completed_at is not None
        assert canonical.duration_ms is not None
        try:
            with self._transaction() as connection:
                self._update_terminal(
                    connection,
                    canonical,
                    expected_current="STARTED",
                )
                for case in canonical.case_results:
                    connection.execute(
                        """INSERT INTO eval_case_results (
                               eval_job_id, case_id, title, status, known_gap,
                               run_ids_json, started_at, completed_at, duration_ms,
                               error_code
                           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            case.eval_job_id,
                            case.case_id,
                            case.title,
                            case.status.value,
                            case.known_gap,
                            json.dumps(case.run_ids, ensure_ascii=False),
                            _utc_text(case.started_at),
                            _utc_text(case.completed_at)
                            if case.completed_at is not None
                            else None,
                            case.duration_ms,
                            case.error_code,
                        ),
                    )
                    for assertion in case.assertions:
                        connection.execute(
                            """INSERT INTO eval_assertion_results (
                                   eval_job_id, case_id, assertion_id, type,
                                   blocking, status, expected_safe_json,
                                   actual_safe_json, message
                               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            (
                                case.eval_job_id,
                                case.case_id,
                                assertion.assertion_id,
                                assertion.type,
                                int(assertion.blocking),
                                assertion.status.value,
                                json.dumps(
                                    assertion.expected_safe,
                                    ensure_ascii=False,
                                    allow_nan=False,
                                )
                                if assertion.expected_safe is not None
                                else None,
                                json.dumps(
                                    assertion.actual_safe,
                                    ensure_ascii=False,
                                    allow_nan=False,
                                )
                                if assertion.actual_safe is not None
                                else None,
                                assertion.message,
                            ),
                        )
                for relation in canonical.case_runs:
                    connection.execute(
                        """INSERT INTO eval_case_runs (
                               eval_job_id, case_id, turn_index, run_id
                           ) VALUES (?, ?, ?, ?)""",
                        (
                            relation.eval_job_id,
                            relation.case_id,
                            relation.turn_index,
                            relation.run_id,
                        ),
                    )
        except EvalPersistenceError:
            raise
        except sqlite3.Error as exc:
            raise EvalPersistenceError(
                "eval job finalization persistence failed"
            ) from exc

    def finalize_failed(self, *, job: EvalJob) -> None:
        canonical = EvalJob.model_validate(job)
        if canonical.lifecycle_status is not EvalJobLifecycleStatus.FAILED:
            raise EvalStateConflictError("eval failure requires FAILED lifecycle")
        assert canonical.completed_at is not None
        assert canonical.duration_ms is not None
        try:
            with self._transaction() as connection:
                self._update_terminal(
                    connection,
                    canonical,
                    expected_current="STARTED",
                )
        except EvalPersistenceError:
            raise
        except sqlite3.Error as exc:
            raise EvalPersistenceError("eval job failure persistence failed") from exc

    def get(self, eval_job_id: str) -> EvalJob | None:
        try:
            connection = self._connect()
            try:
                connection.execute("BEGIN")
                row = connection.execute(
                    "SELECT * FROM eval_jobs WHERE eval_job_id = ?",
                    (eval_job_id,),
                ).fetchone()
                if row is None:
                    connection.commit()
                    return None
                case_rows = connection.execute(
                    """SELECT * FROM eval_case_results
                       WHERE eval_job_id = ? ORDER BY case_id""",
                    (eval_job_id,),
                ).fetchall()
                assertion_rows = connection.execute(
                    """SELECT * FROM eval_assertion_results
                       WHERE eval_job_id = ? ORDER BY case_id, assertion_id""",
                    (eval_job_id,),
                ).fetchall()
                relation_rows = connection.execute(
                    """SELECT eval_job_id, case_id, turn_index, run_id
                       FROM eval_case_runs
                       WHERE eval_job_id = ? ORDER BY case_id, turn_index""",
                    (eval_job_id,),
                ).fetchall()
                connection.commit()
            finally:
                if connection.in_transaction:
                    connection.rollback()
                connection.close()
            return self._detail(row, case_rows, assertion_rows, relation_rows)
        except EvalPersistenceError:
            raise
        except (
            sqlite3.Error,
            ValidationError,
            ValueError,
            TypeError,
            json.JSONDecodeError,
        ) as exc:
            raise EvalDataIntegrityError("stored eval failed typed validation") from exc

    def list(self, *, limit: int) -> list[EvalJobSummary]:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        try:
            connection = self._connect()
            try:
                rows = connection.execute(
                    """SELECT eval_job_id, suite_id, suite_version,
                              lifecycle_status, case_count, passed_count,
                              failed_count, error_count, started_at, completed_at,
                              duration_ms, app_version, build_sha,
                              runtime_identity, error_code
                       FROM eval_jobs
                       ORDER BY started_at DESC, eval_job_id DESC LIMIT ?""",
                    (limit,),
                ).fetchall()
            finally:
                connection.close()
            return [self._summary(row) for row in rows]
        except EvalPersistenceError:
            raise
        except (sqlite3.Error, ValidationError, ValueError, TypeError) as exc:
            raise EvalDataIntegrityError(
                "stored eval list failed typed validation"
            ) from exc

    def _update_terminal(
        self,
        connection: sqlite3.Connection,
        job: EvalJob,
        *,
        expected_current: str,
    ) -> None:
        cursor = connection.execute(
            """UPDATE eval_jobs
               SET lifecycle_status = ?, passed_count = ?, failed_count = ?,
                   error_count = ?, completed_at = ?, duration_ms = ?,
                   error_code = ?
               WHERE eval_job_id = ? AND lifecycle_status = ?""",
            (
                job.lifecycle_status.value,
                job.passed_count,
                job.failed_count,
                job.error_count,
                _utc_text(job.completed_at) if job.completed_at else None,
                job.duration_ms,
                job.error_code,
                job.eval_job_id,
                expected_current,
            ),
        )
        if cursor.rowcount != 1:
            raise EvalStateConflictError("eval job is missing or already terminal")

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
        connection: sqlite3.Connection = self._connect()
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
        with self._initialization_lock, _INITIALIZATION_LOCK:
            if self._initialized:
                return
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                connection = self._new_connection()
                try:
                    connection.execute("PRAGMA journal_mode = WAL")
                    connection.execute("BEGIN IMMEDIATE")
                    connection.execute(
                        """CREATE TABLE IF NOT EXISTS eval_schema_metadata (
                               key TEXT PRIMARY KEY NOT NULL,
                               value TEXT NOT NULL
                           )"""
                    )
                    row = connection.execute(
                        """SELECT value FROM eval_schema_metadata
                           WHERE key = 'eval_schema_version'"""
                    ).fetchone()
                    if row is None:
                        existing = self._table_names(connection)
                        if existing.intersection(
                            _EVAL_DOMAIN_TABLES - {"eval_schema_metadata"}
                        ):
                            raise IncompatibleEvalSchemaError(
                                "eval schema has no version metadata"
                            )
                        for statement in _CREATE_SCHEMA.split(";"):
                            if statement.strip():
                                connection.execute(statement)
                        connection.execute(
                            """INSERT INTO eval_schema_metadata (key, value)
                               VALUES (?, ?)""",
                            ("eval_schema_version", str(EVAL_SCHEMA_VERSION)),
                        )
                    else:
                        try:
                            version = int(row["value"])
                        except (TypeError, ValueError) as exc:
                            raise IncompatibleEvalSchemaError(
                                "eval schema version is invalid"
                            ) from exc
                        if version != EVAL_SCHEMA_VERSION:
                            raise IncompatibleEvalSchemaError(
                                "eval schema version is incompatible"
                            )
                        self._validate_schema(connection)
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
                finally:
                    connection.close()
            except EvalPersistenceError:
                raise
            except (OSError, sqlite3.Error) as exc:
                raise EvalPersistenceError("eval schema initialization failed") from exc
            self._initialized = True

    @staticmethod
    def _table_names(connection: sqlite3.Connection) -> set[str]:
        return {
            str(row["name"])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

    def _validate_schema(self, connection: sqlite3.Connection) -> None:
        table_names = self._table_names(connection)
        if not _EVAL_DOMAIN_TABLES.issubset(table_names):
            raise IncompatibleEvalSchemaError("eval schema tables are incomplete")
        for table, expected in _EXPECTED_COLUMNS.items():
            rows = builtin_list(connection.execute(f"PRAGMA table_info({table})"))
            columns = {str(row["name"]) for row in rows}
            if columns != expected:
                raise IncompatibleEvalSchemaError(
                    f"eval schema table {table} is incompatible"
                )
            actual_not_null = {str(row["name"]) for row in rows if bool(row["notnull"])}
            if actual_not_null != _REQUIRED_NOT_NULL[table]:
                raise IncompatibleEvalSchemaError(
                    f"eval schema table {table} has incompatible nullability"
                )
        self._validate_primary_keys(connection)
        self._validate_foreign_keys(connection)
        self._validate_indexes(connection)
        self._validate_constraints(connection)

    @staticmethod
    def _validate_primary_keys(connection: sqlite3.Connection) -> None:
        for table, expected in _EXPECTED_PRIMARY_KEYS.items():
            rows = builtin_list(connection.execute(f"PRAGMA table_info({table})"))
            actual = tuple(
                str(row["name"])
                for row in sorted(rows, key=lambda row: int(row["pk"]))
                if int(row["pk"]) > 0
            )
            if actual != expected:
                raise IncompatibleEvalSchemaError(
                    f"eval schema table {table} has incompatible primary key"
                )

    @staticmethod
    def _validate_foreign_keys(connection: sqlite3.Connection) -> None:
        for table, expected in _EXPECTED_FOREIGN_KEYS.items():
            rows = builtin_list(connection.execute(f"PRAGMA foreign_key_list({table})"))
            grouped: dict[int, builtin_list[sqlite3.Row]] = {}
            for row in rows:
                grouped.setdefault(int(row["id"]), []).append(row)
            actual = []
            for foreign_key_rows in grouped.values():
                ordered = sorted(
                    foreign_key_rows,
                    key=lambda row: int(row["seq"]),
                )
                actual.append(
                    (
                        str(ordered[0]["table"]),
                        tuple(str(row["from"]) for row in ordered),
                        tuple(str(row["to"]) for row in ordered),
                        str(ordered[0]["on_delete"]).upper(),
                    )
                )
            actual.sort()
            if tuple(actual) != tuple(sorted(expected)):
                raise IncompatibleEvalSchemaError(
                    f"eval schema table {table} has incompatible foreign keys"
                )

    @staticmethod
    def _index_columns(
        connection: sqlite3.Connection,
        index_name: str,
    ) -> tuple[str, ...]:
        escaped_name = index_name.replace('"', '""')
        rows = builtin_list(connection.execute(f'PRAGMA index_info("{escaped_name}")'))
        return tuple(
            str(row["name"]) for row in sorted(rows, key=lambda row: int(row["seqno"]))
        )

    @classmethod
    def _validate_indexes(cls, connection: sqlite3.Connection) -> None:
        for index_name, (
            table,
            expected_columns,
            expected_unique,
        ) in _EXPECTED_INDEXES.items():
            rows = builtin_list(connection.execute(f"PRAGMA index_list({table})"))
            matching = next(
                (row for row in rows if str(row["name"]) == index_name),
                None,
            )
            if matching is None:
                raise IncompatibleEvalSchemaError(
                    f"eval schema index {index_name} is missing"
                )
            if (
                bool(matching["unique"]) != expected_unique
                or cls._index_columns(
                    connection,
                    index_name,
                )
                != expected_columns
            ):
                raise IncompatibleEvalSchemaError(
                    f"eval schema index {index_name} is incompatible"
                )

        for table in _EVAL_DOMAIN_TABLES:
            rows = builtin_list(connection.execute(f"PRAGMA index_list({table})"))
            for row in rows:
                if bool(row["unique"]) and str(row["origin"]) != "pk":
                    raise IncompatibleEvalSchemaError(
                        f"eval schema table {table} has unexpected uniqueness"
                    )

    @staticmethod
    def _validate_constraints(connection: sqlite3.Connection) -> None:
        """Exercise every declared value-domain constraint in a savepoint.

        SQLite exposes CHECK expressions as schema text, but text alone is not
        proof that the constraint is executable.  Valid and invalid probes also
        catch checks that reject one sampled invalid value while allowing other
        values outside the versioned contract.  The savepoint is always rolled
        back, so compatibility reads never modify application data.
        """

        savepoint = "eval_schema_constraints"
        connection.execute(f"SAVEPOINT {savepoint}")
        try:
            for index, lifecycle_status in enumerate(
                ("STARTED", "COMPLETED", "FAILED")
            ):
                SQLiteEvalRepository._probe_job_status(
                    connection,
                    f"__schema_check_job_valid_{index}__",
                    lifecycle_status,
                    should_succeed=True,
                )
            for index, lifecycle_status in enumerate(("INVALID", "OTHER_INVALID")):
                SQLiteEvalRepository._probe_job_status(
                    connection,
                    f"__schema_check_job_invalid_{index}__",
                    lifecycle_status,
                    should_succeed=False,
                )
            for column in (
                "case_count",
                "passed_count",
                "failed_count",
                "error_count",
            ):
                for index, value in enumerate((-1, -2)):
                    SQLiteEvalRepository._probe_job_count(
                        connection,
                        f"__schema_check_count_{column}_{index}__",
                        column,
                        value,
                    )

            parent_job_id = "__schema_check_parent_job__"
            SQLiteEvalRepository._probe_job_status(
                connection,
                parent_job_id,
                "STARTED",
                should_succeed=True,
            )
            for index, status in enumerate(("PASS", "FAIL", "ERROR")):
                SQLiteEvalRepository._probe_case_status(
                    connection,
                    parent_job_id,
                    f"__schema_check_case_valid_{index}__",
                    status,
                    should_succeed=True,
                )
            for index, status in enumerate(("INVALID", "OTHER_INVALID")):
                SQLiteEvalRepository._probe_case_status(
                    connection,
                    parent_job_id,
                    f"__schema_check_case_invalid_{index}__",
                    status,
                    should_succeed=False,
                )
            for index, turn_index in enumerate((0, 1)):
                SQLiteEvalRepository._probe_case_run(
                    connection,
                    parent_job_id,
                    f"__schema_check_relation_{index}__",
                    turn_index,
                    should_succeed=True,
                )
            for index, turn_index in enumerate((-1, -2)):
                SQLiteEvalRepository._probe_case_run(
                    connection,
                    parent_job_id,
                    f"__schema_check_relation_bad_{index}__",
                    turn_index,
                    should_succeed=False,
                )

            valid_case_id = "__schema_check_assertion_case__"
            SQLiteEvalRepository._probe_case_status(
                connection,
                parent_job_id,
                valid_case_id,
                "PASS",
                should_succeed=True,
            )
            for index, blocking in enumerate((0, 1)):
                SQLiteEvalRepository._probe_assertion(
                    connection,
                    parent_job_id,
                    valid_case_id,
                    f"__schema_check_assertion_valid_{index}__",
                    blocking,
                    "PASS",
                    should_succeed=True,
                )
            for index, blocking in enumerate((-1, 2)):
                SQLiteEvalRepository._probe_assertion(
                    connection,
                    parent_job_id,
                    valid_case_id,
                    f"__schema_check_assertion_bad_blocking_{index}__",
                    blocking,
                    "PASS",
                    should_succeed=False,
                )
            for index, status in enumerate(("PASS", "FAIL", "ERROR")):
                SQLiteEvalRepository._probe_assertion(
                    connection,
                    parent_job_id,
                    valid_case_id,
                    f"__schema_check_assertion_status_{index}__",
                    1,
                    status,
                    should_succeed=True,
                )
            for index, status in enumerate(("INVALID", "OTHER_INVALID")):
                SQLiteEvalRepository._probe_assertion(
                    connection,
                    parent_job_id,
                    valid_case_id,
                    f"__schema_check_assertion_bad_status_{index}__",
                    1,
                    status,
                    should_succeed=False,
                )

            SQLiteEvalRepository._probe_foreign_keys(connection)
        finally:
            connection.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
            connection.execute(f"RELEASE SAVEPOINT {savepoint}")

    @staticmethod
    def _probe_job_status(
        connection: sqlite3.Connection,
        job_id: str,
        lifecycle_status: str,
        *,
        should_succeed: bool,
    ) -> None:
        try:
            connection.execute(
                """INSERT INTO eval_jobs (
                       eval_job_id, suite_id, suite_version, lifecycle_status,
                       case_count, passed_count, failed_count, error_count,
                       started_at, app_version, runtime_identity
                   ) VALUES (?, 'schema', '1', ?, 1, 0, 0, 0,
                              '1970-01-01T00:00:00Z', 'schema', 'schema')""",
                (job_id, lifecycle_status),
            )
        except sqlite3.IntegrityError:
            if should_succeed:
                raise IncompatibleEvalSchemaError(
                    "eval_jobs valid lifecycle value is rejected"
                ) from None
        else:
            if not should_succeed:
                raise IncompatibleEvalSchemaError(
                    "eval_jobs invalid lifecycle value is accepted"
                )

    @staticmethod
    def _probe_job_count(
        connection: sqlite3.Connection,
        job_id: str,
        column: str,
        value: int,
    ) -> None:
        if column not in {
            "case_count",
            "passed_count",
            "failed_count",
            "error_count",
        }:
            raise IncompatibleEvalSchemaError("unknown eval count constraint")
        columns = {
            "case_count": "case_count",
            "passed_count": "passed_count",
            "failed_count": "failed_count",
            "error_count": "error_count",
        }
        values = {
            "case_count": 1,
            "passed_count": 0,
            "failed_count": 0,
            "error_count": 0,
        }
        values[column] = value
        try:
            connection.execute(
                """INSERT INTO eval_jobs (
                        eval_job_id, suite_id, suite_version, lifecycle_status,
                        case_count, passed_count, failed_count, error_count,
                        started_at, app_version, runtime_identity
                    ) VALUES (?, 'schema', '1', 'STARTED', ?, ?, ?, ?,
                               '1970-01-01T00:00:00Z', 'schema', 'schema')""",
                (
                    job_id,
                    values[columns["case_count"]],
                    values[columns["passed_count"]],
                    values[columns["failed_count"]],
                    values[columns["error_count"]],
                ),
            )
        except sqlite3.IntegrityError:
            return
        raise IncompatibleEvalSchemaError(f"eval_jobs {column} CHECK is not enforced")

    @staticmethod
    def _probe_case_status(
        connection: sqlite3.Connection,
        job_id: str,
        case_id: str,
        status: str,
        *,
        should_succeed: bool,
    ) -> None:
        try:
            connection.execute(
                """INSERT INTO eval_case_results (
                       eval_job_id, case_id, title, status, run_ids_json,
                       started_at
                   ) VALUES (?, ?, 'schema', ?, '[]',
                              '1970-01-01T00:00:00Z')""",
                (job_id, case_id, status),
            )
        except sqlite3.IntegrityError:
            if should_succeed:
                raise IncompatibleEvalSchemaError(
                    "eval_case_results valid status is rejected"
                ) from None
        else:
            if not should_succeed:
                raise IncompatibleEvalSchemaError(
                    "eval_case_results invalid status is accepted"
                )

    @staticmethod
    def _probe_case_run(
        connection: sqlite3.Connection,
        job_id: str,
        case_id: str,
        turn_index: int,
        *,
        should_succeed: bool,
    ) -> None:
        parent_case_id = f"__schema_check_case_parent_{case_id}__"
        SQLiteEvalRepository._probe_case_status(
            connection,
            job_id,
            parent_case_id,
            "PASS",
            should_succeed=True,
        )
        try:
            connection.execute(
                """INSERT INTO eval_case_runs (
                       eval_job_id, case_id, turn_index, run_id
                   ) VALUES (?, ?, ?, ?)""",
                (job_id, parent_case_id, turn_index, case_id),
            )
        except sqlite3.IntegrityError:
            if should_succeed:
                raise IncompatibleEvalSchemaError(
                    "eval_case_runs valid turn index is rejected"
                ) from None
        else:
            if not should_succeed:
                raise IncompatibleEvalSchemaError(
                    "eval_case_runs invalid turn index is accepted"
                )

    @staticmethod
    def _probe_assertion(
        connection: sqlite3.Connection,
        job_id: str,
        case_id: str,
        assertion_id: str,
        blocking: int,
        status: str,
        *,
        should_succeed: bool,
    ) -> None:
        try:
            connection.execute(
                """INSERT INTO eval_assertion_results (
                       eval_job_id, case_id, assertion_id, type, blocking,
                       status, message
                   ) VALUES (?, ?, ?, 'schema', ?, ?, 'schema')""",
                (job_id, case_id, assertion_id, blocking, status),
            )
        except sqlite3.IntegrityError:
            if should_succeed:
                raise IncompatibleEvalSchemaError(
                    "eval_assertion_results valid value is rejected"
                ) from None
        else:
            if not should_succeed:
                raise IncompatibleEvalSchemaError(
                    "eval_assertion_results invalid value is accepted"
                )

    @staticmethod
    def _probe_foreign_keys(connection: sqlite3.Connection) -> None:
        try:
            connection.execute(
                """INSERT INTO eval_case_results (
                       eval_job_id, case_id, title, status, run_ids_json,
                       started_at
                   ) VALUES ('__schema_check_missing_job__', 'case', 'schema',
                             'PASS', '[]', '1970-01-01T00:00:00Z')"""
            )
        except sqlite3.IntegrityError:
            pass
        else:
            raise IncompatibleEvalSchemaError(
                "eval case result foreign key is not enforced"
            )

        try:
            connection.execute(
                """INSERT INTO eval_case_runs (
                       eval_job_id, case_id, turn_index, run_id
                   ) VALUES ('__schema_check_missing_job__', 'case', 0, 'run')"""
            )
        except sqlite3.IntegrityError:
            pass
        else:
            raise IncompatibleEvalSchemaError(
                "eval case run foreign key is not enforced"
            )

        try:
            connection.execute(
                """INSERT INTO eval_assertion_results (
                       eval_job_id, case_id, assertion_id, type, blocking,
                       status, message
                   ) VALUES ('__schema_check_missing_job__', 'case', 'assertion',
                             'schema', 1, 'PASS', 'schema')"""
            )
        except sqlite3.IntegrityError:
            pass
        else:
            raise IncompatibleEvalSchemaError(
                "eval assertion result foreign key is not enforced"
            )

    @staticmethod
    def _summary(row: sqlite3.Row) -> EvalJobSummary:
        return EvalJobSummary(
            eval_job_id=str(row["eval_job_id"]),
            suite_id=str(row["suite_id"]),
            suite_version=str(row["suite_version"]),
            lifecycle_status=EvalJobLifecycleStatus(str(row["lifecycle_status"])),
            case_count=int(row["case_count"]),
            passed_count=int(row["passed_count"]),
            failed_count=int(row["failed_count"]),
            error_count=int(row["error_count"]),
            started_at=_parse_datetime(row["started_at"]),
            completed_at=(
                _parse_datetime(row["completed_at"])
                if row["completed_at"] is not None
                else None
            ),
            duration_ms=(
                float(row["duration_ms"]) if row["duration_ms"] is not None else None
            ),
            app_version=str(row["app_version"]),
            build_sha=(str(row["build_sha"]) if row["build_sha"] is not None else None),
            runtime_identity=str(row["runtime_identity"]),
            error_code=(
                str(row["error_code"]) if row["error_code"] is not None else None
            ),
        )

    def _detail(
        self,
        row: sqlite3.Row,
        case_rows: builtin_list[sqlite3.Row],
        assertion_rows: builtin_list[sqlite3.Row],
        relation_rows: builtin_list[sqlite3.Row],
    ) -> EvalJob:
        assertions_by_case: dict[str, builtin_list[EvalAssertionResult]] = {}
        for item in assertion_rows:
            assertions_by_case.setdefault(str(item["case_id"]), []).append(
                EvalAssertionResult(
                    assertion_id=str(item["assertion_id"]),
                    type=str(item["type"]),
                    blocking=bool(item["blocking"]),
                    status=str(item["status"]),
                    expected_safe=(
                        json.loads(item["expected_safe_json"])
                        if item["expected_safe_json"] is not None
                        else None
                    ),
                    actual_safe=(
                        json.loads(item["actual_safe_json"])
                        if item["actual_safe_json"] is not None
                        else None
                    ),
                    message=str(item["message"]),
                )
            )
        case_results = [
            EvalCaseResult(
                eval_job_id=str(item["eval_job_id"]),
                case_id=str(item["case_id"]),
                title=str(item["title"]),
                status=EvalCaseStatus(str(item["status"])),
                known_gap=(
                    str(item["known_gap"]) if item["known_gap"] is not None else None
                ),
                run_ids=json.loads(str(item["run_ids_json"])),
                assertions=assertions_by_case.get(str(item["case_id"]), []),
                started_at=_parse_datetime(item["started_at"]),
                completed_at=(
                    _parse_datetime(item["completed_at"])
                    if item["completed_at"] is not None
                    else None
                ),
                duration_ms=(
                    float(item["duration_ms"])
                    if item["duration_ms"] is not None
                    else None
                ),
                error_code=(
                    str(item["error_code"]) if item["error_code"] is not None else None
                ),
            )
            for item in case_rows
        ]
        case_runs = [
            EvalCaseRun(
                eval_job_id=str(item["eval_job_id"]),
                case_id=str(item["case_id"]),
                turn_index=int(item["turn_index"]),
                run_id=str(item["run_id"]),
            )
            for item in relation_rows
        ]
        summary = self._summary(row)
        return EvalJob(
            **summary.model_dump(),
            case_results=case_results,
            case_runs=case_runs,
        )


__all__ = ["EVAL_SCHEMA_VERSION", "SQLiteEvalRepository"]
