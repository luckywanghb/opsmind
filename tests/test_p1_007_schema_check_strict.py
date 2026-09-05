"""Strict independent probe for executable SQLite CHECK validation."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from opsmind.runs import IncompatibleRunSchemaError, SQLiteRunRepository


def _create_v1_with_incomplete_checks(path: Path) -> None:
    """Build checks that reject only the validator's single sampled values."""

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
                lifecycle_status TEXT NOT NULL CHECK (
                    lifecycle_status <> 'INVALID'
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
                sequence INTEGER NOT NULL CHECK (sequence <> -1),
                node TEXT NOT NULL,
                task TEXT NOT NULL,
                profile TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status <> 'invalid'),
                summary TEXT NOT NULL,
                PRIMARY KEY (run_id, sequence),
                FOREIGN KEY (run_id) REFERENCES agent_runs(run_id) ON DELETE CASCADE
            );
            CREATE TABLE evidence_records (
                run_id TEXT NOT NULL,
                sequence INTEGER NOT NULL CHECK (sequence <> -1),
                evidence_id TEXT NOT NULL,
                evidence_json TEXT NOT NULL,
                PRIMARY KEY (run_id, sequence),
                UNIQUE (run_id, evidence_id),
                FOREIGN KEY (run_id) REFERENCES agent_runs(run_id) ON DELETE CASCADE
            );
            CREATE INDEX idx_agent_runs_thread_id ON agent_runs(thread_id);
            CREATE INDEX idx_agent_runs_started_at ON agent_runs(started_at);
            CREATE INDEX idx_agent_runs_lifecycle_status
                ON agent_runs(lifecycle_status);
            """
        )


def test_one_rejected_sample_cannot_prove_complete_required_checks(
    tmp_path: Path,
) -> None:
    """Rejecting one invalid sample does not prove the documented value domain."""

    path = tmp_path / "incomplete-check-v1.db"
    _create_v1_with_incomplete_checks(path)
    repository = SQLiteRunRepository(path)

    try:
        repository.list(limit=1)
    except IncompatibleRunSchemaError:
        return

    # The validator accepted the schema. Demonstrate that every required CHECK
    # it was meant to prove is actually absent and accepts an ordinary value.
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            """INSERT INTO agent_runs (
                   run_id, request_id, thread_id, lifecycle_status,
                   input_message, source_context_json, started_at,
                   runtime_metadata_json
               ) VALUES ('ordinary-run', 'ordinary-request', 'ordinary-thread',
                         'OTHER_INVALID', 'ordinary input', '{}',
                         '1970-01-01T00:00:00Z', '{"app_version":"test"}')"""
        )
        connection.execute(
            """INSERT INTO run_steps
               (run_id, sequence, node, task, profile, status, summary)
               VALUES ('ordinary-run', -2, 'ordinary-node', 'ACTION_DECISION',
                       'HARNESS', 'completed', 'test')"""
        )
        connection.execute(
            """INSERT INTO run_steps
               (run_id, sequence, node, task, profile, status, summary)
               VALUES ('ordinary-run', 0, 'ordinary-node', 'ACTION_DECISION',
                       'HARNESS', 'OTHER_INVALID', 'test')"""
        )
        connection.execute(
            """INSERT INTO evidence_records
               (run_id, sequence, evidence_id, evidence_json)
               VALUES ('ordinary-run', -2, 'E1', '{}')"""
        )

    pytest.fail(
        "schema validation accepted checks that reject only sampled values "
        "while other invalid lifecycle/sequence/status values remain allowed"
    )
