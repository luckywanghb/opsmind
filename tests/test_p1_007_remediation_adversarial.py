"""Independent follow-up probes for TASK-P1-007 remediation."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from opsmind.runs import IncompatibleRunSchemaError, SQLiteRunRepository


def _create_v1_with_partial_unique_indexes(path: Path) -> None:
    """Create a v1-shaped schema whose partial indexes do not ensure uniqueness."""

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
                request_id TEXT NOT NULL,
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
                status TEXT NOT NULL CHECK (
                    status IN ('completed', 'failed', 'blocked')
                ),
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
                FOREIGN KEY (run_id) REFERENCES agent_runs(run_id) ON DELETE CASCADE
            );
            CREATE UNIQUE INDEX partial_request_id_uniqueness
                ON agent_runs(request_id)
                WHERE request_id <> 'UNPROTECTED';
            CREATE UNIQUE INDEX partial_evidence_id_uniqueness
                ON evidence_records(run_id, evidence_id)
                WHERE evidence_id <> 'E1';
            CREATE INDEX idx_agent_runs_thread_id ON agent_runs(thread_id);
            CREATE INDEX idx_agent_runs_started_at ON agent_runs(started_at);
            CREATE INDEX idx_agent_runs_lifecycle_status
                ON agent_runs(lifecycle_status);
            """
        )


def test_partial_unique_indexes_do_not_satisfy_global_uniqueness(
    tmp_path: Path,
) -> None:
    """Version validation must reject uniqueness that applies to only some rows."""

    path = tmp_path / "partial-unique-v1.db"
    _create_v1_with_partial_unique_indexes(path)

    with pytest.raises(IncompatibleRunSchemaError):
        SQLiteRunRepository(path).list(limit=1)
