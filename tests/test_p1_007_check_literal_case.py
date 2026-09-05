"""Regression for case-sensitive SQLite CHECK literals."""

from pathlib import Path

import pytest

from opsmind.runs import IncompatibleRunSchemaError, SQLiteRunRepository


def test_uppercase_step_status_literals_are_not_accepted_as_v1_schema(
    tmp_path: Path,
) -> None:
    path = tmp_path / "uppercase-status.db"
    repository = SQLiteRunRepository(path)
    repository.list(limit=1)
    # Replace only the status CHECK literals while preserving the rest of the
    # canonical schema, then ensure compatibility validation rejects it.
    import sqlite3

    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA writable_schema = ON")
        row = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='run_steps'"
        ).fetchone()
        assert row is not None
        sql = str(row[0]).replace(
            "'completed', 'failed', 'blocked'", "'COMPLETED', 'FAILED', 'BLOCKED'"
        )
        connection.execute(
            "UPDATE sqlite_master SET sql = ? WHERE type='table' AND name='run_steps'",
            (sql,),
        )
        connection.execute("PRAGMA writable_schema = OFF")
        connection.commit()

    with pytest.raises(IncompatibleRunSchemaError):
        SQLiteRunRepository(path).list(limit=1)
