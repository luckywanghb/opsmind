"""Developer tests for the Agent-run repository and lifecycle service."""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from opsmind.models import ModelProfile, ModelTask
from opsmind.runs import (
    SCHEMA_VERSION,
    AgentRun,
    IncompatibleRunSchemaError,
    RunAlreadyExistsError,
    RunDataIntegrityError,
    RunLifecycleStatus,
    RunPersistenceError,
    RunPersistenceService,
    RunStep,
    RuntimeMetadata,
    SafeSourceContext,
    SQLiteRunRepository,
)
from opsmind.state import (
    AgentAction,
    DecisionState,
    EvidenceItem,
    HandoffState,
    PrimaryIntent,
    RequestType,
    RiskSignal,
    UnderstandingState,
)

NOW = datetime(2026, 9, 5, 4, 0, tzinfo=UTC)


def _started(
    *,
    run_id: str = "run-1",
    request_id: str = "request-1",
    thread_id: str = "thread-1",
    started_at: datetime = NOW,
) -> AgentRun:
    return AgentRun(
        run_id=run_id,
        request_id=request_id,
        thread_id=thread_id,
        lifecycle_status=RunLifecycleStatus.STARTED,
        input_message=f"input:{run_id}",
        source_context=SafeSourceContext(
            channel="portal", user_id="U10023", site_id="SITE-1"
        ),
        started_at=started_at,
        runtime_metadata=RuntimeMetadata(app_version="0.1.0"),
    )


def _understanding() -> UnderstandingState:
    return UnderstandingState(
        primary_intent=PrimaryIntent.WORKFLOW_ISSUE,
        request_type=RequestType.DIAGNOSE,
        symptom="waiting",
        entities={"work_order_id": "WO20260001"},
        risk_signal=RiskSignal.NONE,
        uncertainty=None,
    )


def _decision(action: AgentAction = AgentAction.REPLY) -> DecisionState:
    return DecisionState(action=action, goal="reply", rationale="evidence ready")


def _step(sequence: int = 0) -> RunStep:
    return RunStep(
        sequence=sequence,
        node="understand_request",
        task=ModelTask.REQUEST_UNDERSTANDING,
        profile=ModelProfile.CHEAP,
        status="completed",
        summary="WORKFLOW_ISSUE / DIAGNOSE",
    )


def _evidence() -> EvidenceItem:
    return EvidenceItem(
        evidence_id="E1",
        source="work_order_query",
        summary="work_order_query: found",
        key_fields={"status": "APPROVING", "abnormal": False},
        metadata={"result_status": "found", "reviewed": True},
        timestamp=NOW,
    )


def _succeeded(started: AgentRun) -> AgentRun:
    return AgentRun.model_validate(
        started.model_copy(
            update={
                "lifecycle_status": RunLifecycleStatus.SUCCEEDED,
                "agent_terminal_status": "completed",
                "understanding": _understanding(),
                "decision": _decision(),
                "final_reply": "source-grounded reply",
                "handoff": None,
                "completed_at": NOW + timedelta(milliseconds=12),
                "duration_ms": 12.0,
                "runtime_metadata": RuntimeMetadata(
                    app_version="0.1.0",
                    logical_model_profiles=[ModelProfile.CHEAP],
                ),
                "steps": [_step()],
                "evidence": [_evidence()],
            }
        )
    )


def _failed(started: AgentRun) -> AgentRun:
    return AgentRun.model_validate(
        started.model_copy(
            update={
                "lifecycle_status": RunLifecycleStatus.FAILED,
                "completed_at": NOW + timedelta(milliseconds=3),
                "duration_ms": 3.0,
                "error_code": "MODEL_STRUCTURED_OUTPUT_INVALID",
                "steps": [
                    RunStep(
                        sequence=0,
                        node="decide_action",
                        task=ModelTask.ACTION_DECISION,
                        profile=ModelProfile.CHEAP,
                        status="failed",
                        summary="MODEL_STRUCTURED_OUTPUT_INVALID",
                    )
                ],
            }
        )
    )


def test_fresh_schema_initialization_is_versioned_and_idempotent(
    tmp_path: Path,
) -> None:
    path = tmp_path / "nested" / "opsmind.db"
    first = SQLiteRunRepository(path)
    first.create_started(_started())

    second = SQLiteRunRepository(path)
    assert second.get("run-1") == _started()

    with sqlite3.connect(path) as connection:
        version = connection.execute(
            "SELECT value FROM schema_metadata WHERE key = 'schema_version'"
        ).fetchone()
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        indexes = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            )
        }

    assert version == (str(SCHEMA_VERSION),)
    assert {"agent_runs", "run_steps", "evidence_records"} <= tables
    assert {
        "idx_agent_runs_thread_id",
        "idx_agent_runs_started_at",
        "idx_agent_runs_lifecycle_status",
    } <= indexes


def test_incompatible_schema_version_fails_explicitly(tmp_path: Path) -> None:
    path = tmp_path / "opsmind.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE schema_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO schema_metadata (key, value) VALUES ('schema_version', '999')"
        )

    with pytest.raises(IncompatibleRunSchemaError):
        SQLiteRunRepository(path).list(limit=1)


def test_run_lifecycle_success_and_failure_round_trip(tmp_path: Path) -> None:
    repository = SQLiteRunRepository(tmp_path / "opsmind.db")
    success_start = _started()
    failed_start = _started(run_id="run-2", request_id="request-2")
    repository.create_started(success_start)
    repository.create_started(failed_start)

    repository.finalize_succeeded(run=_succeeded(success_start))
    repository.finalize_failed(run=_failed(failed_start))

    success = repository.get("run-1")
    failed = repository.get("run-2")
    assert success == _succeeded(success_start)
    assert success is not None and success.evidence[0].evidence_id == "E1"
    assert failed == _failed(failed_start)
    assert failed is not None and failed.understanding is None


def test_run_and_request_identifiers_are_unique(tmp_path: Path) -> None:
    repository = SQLiteRunRepository(tmp_path / "opsmind.db")
    repository.create_started(_started())

    with pytest.raises(RunAlreadyExistsError):
        repository.create_started(_started(request_id="request-other"))
    with pytest.raises(RunAlreadyExistsError):
        repository.create_started(_started(run_id="run-other"))


def test_list_is_newest_first_and_honors_limit(tmp_path: Path) -> None:
    repository = SQLiteRunRepository(tmp_path / "opsmind.db")
    for offset in range(3):
        repository.create_started(
            _started(
                run_id=f"run-{offset}",
                request_id=f"request-{offset}",
                started_at=NOW + timedelta(seconds=offset),
            )
        )

    assert [item.run_id for item in repository.list(limit=2)] == ["run-2", "run-1"]


def test_finalize_rolls_back_status_steps_and_evidence_together(
    tmp_path: Path,
) -> None:
    path = tmp_path / "opsmind.db"
    repository = SQLiteRunRepository(path)
    started = _started()
    repository.create_started(started)
    with sqlite3.connect(path) as connection:
        connection.execute(
            """CREATE TRIGGER reject_evidence BEFORE INSERT ON evidence_records
               BEGIN SELECT RAISE(ABORT, 'injected failure'); END"""
        )

    with pytest.raises(RunPersistenceError):
        repository.finalize_succeeded(run=_succeeded(started))

    assert repository.get("run-1") == started
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM run_steps").fetchone() == (0,)
        assert connection.execute(
            "SELECT COUNT(*) FROM evidence_records"
        ).fetchone() == (0,)


def test_malformed_stored_json_fails_the_typed_read_boundary(
    tmp_path: Path,
) -> None:
    path = tmp_path / "opsmind.db"
    repository = SQLiteRunRepository(path)
    started = _started()
    repository.create_started(started)
    repository.finalize_succeeded(run=_succeeded(started))
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE agent_runs SET understanding_json = ? WHERE run_id = ?",
            ('{"unexpected":"RAW_PROVIDER_SENTINEL"}', started.run_id),
        )

    with pytest.raises(RunDataIntegrityError):
        repository.get(started.run_id)


def test_service_uses_monotonic_timing_and_allowlists_source_context(
    tmp_path: Path,
) -> None:
    ticks = iter([10.0, 10.025])
    repository = SQLiteRunRepository(tmp_path / "opsmind.db")
    service = RunPersistenceService(
        repository,
        app_version="0.1.0",
        utc_now=lambda: NOW,
        monotonic=lambda: next(ticks),
    )
    active = service.start(
        request_id="request-service",
        thread_id="thread-service",
        input_message="hello",
        source_context={
            "channel": "portal",
            "user_id": "U10023",
            "site_id": "SITE-1",
            "authorization": "PROMPT_SECRET_SENTINEL",
            "nested": {"raw": "PROVIDER_PAYLOAD_SENTINEL"},
        },
    )
    service.succeed(
        active,
        terminal_status="transferred",
        understanding=_understanding(),
        decision=_decision(AgentAction.TRANSFER_HUMAN),
        final_reply="safe handoff",
        handoff=HandoffState(required=True, summary="safe handoff"),
        steps=[_step()],
        evidence=[_evidence()],
    )

    stored = service.get(active.run_id)
    assert stored.duration_ms == pytest.approx(25.0)
    assert stored.source_context.model_dump(exclude_none=True) == {
        "channel": "portal",
        "user_id": "U10023",
        "site_id": "SITE-1",
    }
    assert stored.runtime_metadata.logical_model_profiles == [ModelProfile.CHEAP]


def test_concurrent_runs_remain_isolated(tmp_path: Path) -> None:
    repository = SQLiteRunRepository(tmp_path / "opsmind.db")
    service = RunPersistenceService(repository, app_version="0.1.0")

    def execute(index: int) -> str:
        active = service.start(
            request_id=f"request-{index}",
            thread_id=f"thread-{index}",
            input_message=f"message-{index}",
            source_context={"channel": "test"},
        )
        evidence = _evidence().model_copy(
            update={
                "key_fields": {"marker": index},
                "timestamp": NOW + timedelta(seconds=index),
            }
        )
        service.succeed(
            active,
            terminal_status="completed",
            understanding=_understanding(),
            decision=_decision(),
            final_reply=f"reply-{index}",
            handoff=None,
            steps=[_step()],
            evidence=[EvidenceItem.model_validate(evidence)],
        )
        return active.run_id

    with ThreadPoolExecutor(max_workers=8) as executor:
        run_ids = list(executor.map(execute, range(12)))

    assert len(run_ids) == len(set(run_ids)) == 12
    stored = [service.get(run_id) for run_id in run_ids]
    assert {
        (run.thread_id, run.final_reply, run.evidence[0].key_fields["marker"])
        for run in stored
    } == {(f"thread-{index}", f"reply-{index}", index) for index in range(12)}
