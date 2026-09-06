from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from opsmind.evals import (
    EvalAssertionResult,
    EvalAssertionStatus,
    EvalCaseResult,
    EvalCaseStatus,
    EvalJobLifecycleStatus,
    EvalPersistenceService,
    IncompatibleEvalSchemaError,
    SQLiteEvalRepository,
)
from opsmind.runs import RunPersistenceService, SQLiteRunRepository


def _case_result(job_id: str, *, run_id: str) -> EvalCaseResult:
    started = datetime.now(UTC)
    return EvalCaseResult(
        eval_job_id=job_id,
        case_id="C01",
        title="case",
        status=EvalCaseStatus.PASS,
        run_ids=[run_id],
        assertions=[
            EvalAssertionResult(
                assertion_id="lifecycle",
                type="run_lifecycle_succeeded",
                blocking=True,
                status=EvalAssertionStatus.PASS,
                expected_safe=True,
                actual_safe=True,
                message="run lifecycle checked",
            )
        ],
        started_at=started,
        completed_at=datetime.now(UTC),
        duration_ms=1.0,
    )


def _real_run(path: Path, *, suffix: str = "1") -> str:
    runs = SQLiteRunRepository(path)
    service = RunPersistenceService(runs, app_version="test")
    active = service.start(
        request_id=f"request-{suffix}",
        thread_id=f"thread-{suffix}",
        input_message="test",
        source_context={"channel": "test"},
    )
    service.fail(active, error_code="MODEL_INVOCATION_FAILED")
    return active.run_id


def test_eval_job_completion_is_transactional_and_links_real_runs(
    tmp_path: Path,
) -> None:
    path = tmp_path / "opsmind.db"
    run_id = _real_run(path)
    repository = SQLiteEvalRepository(path)
    persistence = EvalPersistenceService(
        repository,
        app_version="test",
        run_repository=SQLiteRunRepository(path),
    )
    active = persistence.start(
        suite_id="test-suite",
        suite_version="1.0",
        case_count=1,
        runtime_identity="mock",
    )
    result = persistence.complete(
        active, case_results=[_case_result(active.eval_job_id, run_id=run_id)]
    )

    assert result.lifecycle_status is EvalJobLifecycleStatus.COMPLETED
    assert result.passed_count == 1
    loaded = repository.get(result.eval_job_id)
    assert loaded is not None
    assert loaded.case_results[0].run_ids == [run_id]
    assert loaded.case_runs[0].run_id == run_id
    assert loaded.case_results[0].assertions[0].status is EvalAssertionStatus.PASS

    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT value FROM schema_metadata WHERE key = 'schema_version'"
        ).fetchone() == ("1",)
        assert connection.execute(
            "SELECT value FROM eval_schema_metadata WHERE key = 'eval_schema_version'"
        ).fetchone() == ("1",)


def test_eval_job_completion_inserts_all_case_parents_before_run_links(
    tmp_path: Path,
) -> None:
    path = tmp_path / "opsmind.db"
    run_id_1 = _real_run(path, suffix="1")
    run_id_2 = _real_run(path, suffix="2")
    repository = SQLiteEvalRepository(path)
    persistence = EvalPersistenceService(
        repository,
        app_version="test",
        run_repository=SQLiteRunRepository(path),
    )
    active = persistence.start(
        suite_id="test-suite",
        suite_version="1.0",
        case_count=2,
        runtime_identity="mock",
    )
    results = [
        _case_result(active.eval_job_id, run_id=run_id_1),
        _case_result(active.eval_job_id, run_id=run_id_2).model_copy(
            update={"case_id": "C02"}
        ),
    ]

    completed = persistence.complete(active, case_results=results)

    assert completed.lifecycle_status is EvalJobLifecycleStatus.COMPLETED
    assert {item.case_id for item in completed.case_results} == {"C01", "C02"}
    assert {item.case_id for item in completed.case_runs} == {"C01", "C02"}


def test_eval_persistence_rejects_orphan_run_reference(tmp_path: Path) -> None:
    path = tmp_path / "opsmind.db"
    repository = SQLiteEvalRepository(path)
    persistence = EvalPersistenceService(
        repository,
        app_version="test",
        run_repository=SQLiteRunRepository(path),
    )
    active = persistence.start(
        suite_id="test-suite",
        suite_version="1.0",
        case_count=1,
        runtime_identity="mock",
    )

    with pytest.raises(Exception, match="Agent run reference"):
        persistence.complete(
            active,
            case_results=[_case_result(active.eval_job_id, run_id="missing-run")],
        )

    assert repository.get(active.eval_job_id) is not None
    assert (
        repository.get(active.eval_job_id).lifecycle_status
        is EvalJobLifecycleStatus.STARTED
    )  # type: ignore[union-attr]


def test_eval_schema_is_revalidated_by_a_new_repository(tmp_path: Path) -> None:
    path = tmp_path / "opsmind.db"
    SQLiteEvalRepository(path).list(limit=1)

    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE UNIQUE INDEX unexpected_eval_uniqueness ON eval_jobs(suite_id)"
        )

    with pytest.raises(IncompatibleEvalSchemaError):
        SQLiteEvalRepository(path).list(limit=1)
