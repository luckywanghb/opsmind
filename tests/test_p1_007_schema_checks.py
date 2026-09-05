"""Regression tests for executable version-1 SQLite CHECK constraints."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from opsmind.runs import IncompatibleRunSchemaError, SQLiteRunRepository


def _create_schema_with_check_looking_text(path: Path) -> None:
    """Create a constrained-shaped schema with CHECK text only as noise."""

    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE schema_metadata (
                key TEXT PRIMARY KEY NOT NULL,
                value TEXT NOT NULL
            );
            INSERT INTO schema_metadata (key, value) VALUES ('schema_version', '1');
            CREATE TABLE agent_runs (
                run_id TEXT PRIMARY KEY NOT NULL,
                request_id TEXT NOT NULL UNIQUE,
                thread_id TEXT NOT NULL,
                lifecycle_status TEXT NOT NULL
                    /* CHECK (lifecycle_status IN
                       ('STARTED', 'SUCCEEDED', 'FAILED')) */,
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
                sequence INTEGER NOT NULL DEFAULT 0
                    /* CHECK (sequence >= 0) */,
                node TEXT NOT NULL,
                task TEXT NOT NULL,
                profile TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT
                    'CHECK (status IN (''completed'', ''failed'', ''blocked''))',
                summary TEXT NOT NULL,
                PRIMARY KEY (run_id, sequence),
                FOREIGN KEY (run_id) REFERENCES agent_runs(run_id)
                    ON DELETE CASCADE
            );
            CREATE TABLE evidence_records (
                run_id TEXT NOT NULL,
                sequence INTEGER NOT NULL
                    /* CHECK (sequence >= 0) */,
                evidence_id TEXT NOT NULL,
                evidence_json TEXT NOT NULL,
                PRIMARY KEY (run_id, sequence),
                UNIQUE (run_id, evidence_id),
                FOREIGN KEY (run_id) REFERENCES agent_runs(run_id)
                    ON DELETE CASCADE
            );
            CREATE INDEX idx_agent_runs_thread_id ON agent_runs(thread_id);
            CREATE INDEX idx_agent_runs_started_at ON agent_runs(started_at);
            CREATE INDEX idx_agent_runs_lifecycle_status
                ON agent_runs(lifecycle_status);
            """
        )


def test_check_looking_comments_and_strings_are_not_constraints(
    tmp_path: Path,
) -> None:
    path = tmp_path / "fake-check-v1.db"
    _create_schema_with_check_looking_text(path)

    with pytest.raises(IncompatibleRunSchemaError):
        SQLiteRunRepository(path).list(limit=1)


def test_v1_checks_reject_invalid_lifecycle_and_child_values(tmp_path: Path) -> None:
    path = tmp_path / "real-check-v1.db"
    repository = SQLiteRunRepository(path)
    repository.list(limit=1)

    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            """INSERT INTO agent_runs (
                   run_id, request_id, thread_id, lifecycle_status,
                   input_message, source_context_json, started_at,
                   runtime_metadata_json
               ) VALUES ('valid-run', 'valid-request', 'valid-thread', 'STARTED',
                         'test', '{}', '1970-01-01T00:00:00Z',
                         '{"app_version":"test"}')"""
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """INSERT INTO agent_runs (
                       run_id, request_id, thread_id, lifecycle_status,
                       input_message, source_context_json, started_at,
                       runtime_metadata_json
                   ) VALUES ('bad-lifecycle', 'bad-lifecycle-request',
                             'valid-thread', 'INVALID', 'test', '{}',
                             '1970-01-01T00:00:00Z', '{"app_version":"test"}')"""
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """INSERT INTO run_steps
                   (run_id, sequence, node, task, profile, status, summary)
                   VALUES ('valid-run', -1, 'node', 'ACTION_DECISION', 'HARNESS',
                           'completed', 'test')"""
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """INSERT INTO run_steps
                   (run_id, sequence, node, task, profile, status, summary)
                   VALUES ('valid-run', 0, 'node', 'ACTION_DECISION', 'HARNESS',
                           'INVALID', 'test')"""
            )
