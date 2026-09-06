"""Regression for destructive extra uniqueness in schema version 1."""

import sqlite3
from pathlib import Path

import pytest

from opsmind.runs import IncompatibleRunSchemaError, SQLiteRunRepository


def test_extra_thread_id_uniqueness_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "extra-thread-unique.db"
    repository = SQLiteRunRepository(path)
    repository.list(limit=1)

    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE UNIQUE INDEX unexpected_thread_uniqueness "
            "ON agent_runs(thread_id)"
        )

    with pytest.raises(IncompatibleRunSchemaError):
        SQLiteRunRepository(path).list(limit=1)
