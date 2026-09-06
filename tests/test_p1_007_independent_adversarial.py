"""Independent adversarial probes for TASK-P1-007.

These tests deliberately target lifecycle and SQLite integrity boundaries not
covered by the Developer-authored happy-path suite.  They are test-only: no
product implementation is replaced or relaxed here.
"""

from __future__ import annotations

import importlib
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from opsmind.api.app import create_app
from opsmind.models import ModelProfile, ModelTask
from opsmind.runs import (
    AgentRun,
    IncompatibleRunSchemaError,
    RunDataIntegrityError,
    RunLifecycleStatus,
    RunPersistenceError,
    RunPersistenceService,
    RunStep,
    SQLiteRunRepository,
)
from opsmind.state import (
    AgentAction,
    DecisionState,
    EvidenceItem,
    PrimaryIntent,
    RequestType,
    UnderstandingState,
)


def test_post_start_state_construction_failure_is_finalized_failed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every unexpected post-STARTED failure must leave a FAILED run."""

    repository = SQLiteRunRepository(tmp_path / "opsmind.db")
    app_module = importlib.import_module("opsmind.api.app")

    def fail_state_construction(**_: object) -> None:
        raise RuntimeError("TRACEBACK_SECRET_SENTINEL")

    monkeypatch.setattr(app_module, "OpsAgentState", fail_state_construction)
    client = TestClient(
        create_app(run_repository=repository),
        raise_server_exceptions=False,
    )

    response = client.post("/api/v1/chat", json={"message": "valid request"})

    assert response.status_code == 500
    assert "TRACEBACK_SECRET_SENTINEL" not in response.text
    run_id = response.json()["error"]["run_id"]
    stored = repository.get(run_id)
    assert stored is not None
    assert stored.lifecycle_status is RunLifecycleStatus.FAILED
    assert stored.error_code == "INTERNAL_SERVER_ERROR"


class _PauseAfterParentCursor:
    def __init__(
        self,
        cursor: sqlite3.Cursor,
        parent_read: threading.Event,
        finalization_done: threading.Event,
    ) -> None:
        self._cursor = cursor
        self._parent_read = parent_read
        self._finalization_done = finalization_done

    def fetchone(self) -> sqlite3.Row | None:
        row = self._cursor.fetchone()
        self._parent_read.set()
        assert self._finalization_done.wait(timeout=5), "writer did not finalize"
        return row


class _PauseAfterParentConnection:
    def __init__(
        self,
        connection: sqlite3.Connection,
        parent_read: threading.Event,
        finalization_done: threading.Event,
    ) -> None:
        self._connection = connection
        self._parent_read = parent_read
        self._finalization_done = finalization_done

    def execute(
        self,
        sql: str,
        parameters: tuple[object, ...] = (),
    ) -> sqlite3.Cursor | _PauseAfterParentCursor:
        cursor = self._connection.execute(sql, parameters)
        if sql.strip().startswith("SELECT * FROM agent_runs WHERE run_id"):
            return _PauseAfterParentCursor(
                cursor,
                self._parent_read,
                self._finalization_done,
            )
        return cursor

    def __getattr__(self, name: str) -> Any:
        return getattr(self._connection, name)


class _PausingReadRepository(SQLiteRunRepository):
    def __init__(
        self,
        path: Path,
        parent_read: threading.Event,
        finalization_done: threading.Event,
    ) -> None:
        super().__init__(path)
        self._parent_read = parent_read
        self._finalization_done = finalization_done

    def _new_connection(self) -> Any:
        connection = super()._new_connection()
        return _PauseAfterParentConnection(
            connection,
            self._parent_read,
            self._finalization_done,
        )


def test_get_uses_one_consistent_snapshot_during_success_finalization(
    tmp_path: Path,
) -> None:
    """A valid concurrent commit must not produce a spurious integrity error."""

    path = tmp_path / "opsmind.db"
    writer_repository = SQLiteRunRepository(path)
    writer_service = RunPersistenceService(writer_repository, app_version="tester")
    active = writer_service.start(
        request_id="request-race",
        thread_id="thread-race",
        input_message="race",
        source_context={"channel": "tester"},
    )

    parent_read = threading.Event()
    finalization_done = threading.Event()
    reader_repository = _PausingReadRepository(
        path,
        parent_read,
        finalization_done,
    )

    def read_detail() -> AgentRun | None:
        return reader_repository.get(active.run_id)

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(read_detail)
        assert parent_read.wait(timeout=5), "reader did not fetch the parent row"
        writer_service.succeed(
            active,
            terminal_status="completed",
            understanding=UnderstandingState(
                primary_intent=PrimaryIntent.OTHER,
                request_type=RequestType.OTHER,
            ),
            decision=DecisionState(
                action=AgentAction.REPLY,
                goal="reply",
                rationale="done",
            ),
            final_reply="safe reply",
            handoff=None,
            steps=[
                RunStep(
                    sequence=0,
                    node="generate_response",
                    task=ModelTask.RESPONSE_GENERATION,
                    profile=ModelProfile.CHEAP,
                    status="completed",
                    summary="done",
                )
            ],
            evidence=[
                EvidenceItem(
                    evidence_id="E1",
                    source="tester",
                    summary="typed evidence",
                    timestamp=datetime.now(UTC),
                )
            ],
        )
        finalization_done.set()
        try:
            observed = future.result(timeout=5)
        except RunDataIntegrityError as exc:  # make the failure diagnosis explicit
            pytest.fail(f"valid concurrent finalization crossed read snapshots: {exc}")

    assert observed is not None
    # Either a coherent pre-commit STARTED snapshot or a coherent post-commit
    # SUCCEEDED snapshot is valid; a mixture is not.
    assert observed.lifecycle_status in {
        RunLifecycleStatus.STARTED,
        RunLifecycleStatus.SUCCEEDED,
    }


def _create_constraintless_v1_schema(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE schema_metadata (key TEXT, value TEXT);
            INSERT INTO schema_metadata (key, value) VALUES ('schema_version', '1');
            CREATE TABLE agent_runs (
                run_id TEXT, request_id TEXT, thread_id TEXT,
                lifecycle_status TEXT, agent_terminal_status TEXT,
                input_message TEXT, source_context_json TEXT,
                understanding_json TEXT, decision_json TEXT, final_reply TEXT,
                handoff_json TEXT, started_at TEXT, completed_at TEXT,
                duration_ms REAL, error_code TEXT, runtime_metadata_json TEXT
            );
            CREATE TABLE run_steps (
                run_id TEXT, sequence INTEGER, node TEXT, task TEXT,
                profile TEXT, status TEXT, summary TEXT
            );
            CREATE TABLE evidence_records (
                run_id TEXT, sequence INTEGER, evidence_id TEXT,
                evidence_json TEXT
            );
            """
        )


def test_declared_v1_schema_without_required_constraints_is_rejected(
    tmp_path: Path,
) -> None:
    """A version label alone must not bless a schema lacking audit invariants."""

    path = tmp_path / "hollow-v1.db"
    _create_constraintless_v1_schema(path)

    with pytest.raises(IncompatibleRunSchemaError):
        SQLiteRunRepository(path).list(limit=1)


def test_malformed_typed_snapshot_returns_safe_503_without_stored_text(
    tmp_path: Path,
) -> None:
    """Corrupt JSON is rejected at the HTTP boundary without reflecting it."""

    path = tmp_path / "opsmind.db"
    repository = SQLiteRunRepository(path)
    client = TestClient(
        create_app(run_repository=repository),
        raise_server_exceptions=False,
    )
    chat = client.post("/api/v1/chat", json={"message": "close this request"})
    assert chat.status_code == 200
    run_id = chat.json()["run_id"]

    sentinel = "MALFORMED_PROVIDER_PAYLOAD_SENTINEL"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE agent_runs SET decision_json = ? WHERE run_id = ?",
            (f'{{"unexpected":"{sentinel}"}}', run_id),
        )

    response = client.get(f"/api/v1/runs/{run_id}")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "RUN_PERSISTENCE_UNAVAILABLE"
    assert sentinel not in response.text


def test_failed_finalization_rolls_back_parent_and_steps_together(
    tmp_path: Path,
) -> None:
    """The FAILED path is atomic when child-step insertion fails."""

    path = tmp_path / "opsmind.db"
    repository = SQLiteRunRepository(path)
    service = RunPersistenceService(repository, app_version="tester")
    active = service.start(
        request_id="request-failed-rollback",
        thread_id="thread-failed-rollback",
        input_message="fail",
        source_context={},
    )
    with sqlite3.connect(path) as connection:
        connection.execute(
            """CREATE TRIGGER reject_failed_step BEFORE INSERT ON run_steps
               BEGIN SELECT RAISE(ABORT, 'injected failure'); END"""
        )

    with pytest.raises(RunPersistenceError):
        service.fail(
            active,
            error_code="INTERNAL_SERVER_ERROR",
            steps=[
                RunStep(
                    sequence=0,
                    node="tester",
                    task=ModelTask.ACTION_DECISION,
                    profile="HARNESS",
                    status="failed",
                    summary="INTERNAL_SERVER_ERROR",
                )
            ],
        )

    assert repository.get(active.run_id) == active.started
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM run_steps").fetchone() == (0,)


def test_concurrent_first_use_across_repository_instances_is_isolated(
    tmp_path: Path,
) -> None:
    """SQLite locking also covers separate repository objects in one process."""

    path = tmp_path / "opsmind.db"
    barrier = threading.Barrier(8)

    def execute(index: int) -> str:
        repository = SQLiteRunRepository(path)
        service = RunPersistenceService(repository, app_version="tester")
        barrier.wait(timeout=5)
        active = service.start(
            request_id=f"request-multi-repo-{index}",
            thread_id=f"thread-multi-repo-{index}",
            input_message=f"message-{index}",
            source_context={"channel": "tester"},
        )
        service.fail(active, error_code="INTERNAL_SERVER_ERROR")
        return active.run_id

    with ThreadPoolExecutor(max_workers=8) as executor:
        run_ids = list(executor.map(execute, range(8)))

    assert len(run_ids) == len(set(run_ids)) == 8
    runs = SQLiteRunRepository(path).list(limit=8)
    assert len(runs) == 8
    assert {run.lifecycle_status for run in runs} == {RunLifecycleStatus.FAILED}
