from __future__ import annotations

import json
from pathlib import Path

import pytest

from opsmind.evals import EvalSuiteLoader, EvalSuiteLoadError


def _suite_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "suite_id": "test-suite",
        "suite_version": "1.0",
        "description": "test suite",
        "cases": [
            {
                "case_id": "C1",
                "title": "one",
                "turns": [{"message": "hello"}],
                "source_context": {"channel": "test"},
                "assertions": [
                    {
                        "assertion_id": "a1",
                        "type": "reply_nonempty",
                        "expected": True,
                    }
                ],
            }
        ],
    }


def test_backend_golden_suite_is_typed_versioned_and_deterministic() -> None:
    loader = EvalSuiteLoader()
    first = loader.load()
    second = loader.load()

    assert first.suite_id == "opsmind-golden"
    assert first.suite_version == "0.3"
    assert [case.case_id for case in first.cases] == [
        "C01",
        "C03",
        "C05",
        "C06",
        "C09",
        "C10",
        "C11",
        "C12",
        "C13",
    ]
    assert first.model_dump_json() == second.model_dump_json()

    c12 = next(case for case in first.cases if case.case_id == "C12")
    assert c12.known_gap is None
    assert [turn.message for turn in c12.turns] == [
        "WO20260001为什么一直没处理？",
        "那现在是谁在处理？",
    ]


def test_backend_golden_suite_contains_pm_owned_c05_and_c06_truth() -> None:
    suite = EvalSuiteLoader().load()
    cases = {case.case_id: case for case in suite.cases}

    c05 = {assertion.assertion_id: assertion for assertion in cases["C05"].assertions}
    assert c05["handler"].blocking is True
    assert c05["handler"].expected == {
        "source": "work_order_query",
        "field": "current_handler",
        "value": "U10108",
    }
    assert c05["waiting"].blocking is True
    assert c05["waiting"].expected == {
        "source": "work_order_query",
        "field": "waiting_hours",
        "value": 4,
    }

    c06 = {assertion.assertion_id: assertion for assertion in cases["C06"].assertions}
    assert c06["request"].blocking is True
    assert c06["request"].expected == ["DIAGNOSE"]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload["cases"].append(payload["cases"][0]),
        lambda payload: payload["cases"][0]["assertions"].append(
            payload["cases"][0]["assertions"][0]
        ),
        lambda payload: payload["cases"][0]["assertions"][0].update(
            {"type": "unknown_evaluator"}
        ),
        lambda payload: payload.update({"schema_version": 999}),
        lambda payload: payload.update({"cases": []}),
        lambda payload: payload["cases"][0].update({"source_context": []}),
    ],
)
def test_suite_integrity_failures_are_explicit(mutate: object) -> None:
    payload = _suite_payload()
    # The lambdas are deliberately data-only mutations; the loader remains the
    # single validation boundary under test.
    mutate(payload)  # type: ignore[operator]

    with pytest.raises(EvalSuiteLoadError):
        EvalSuiteLoader().loads(json.dumps(payload))


def test_oversized_suite_file_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "oversized.json"
    payload = _suite_payload()
    payload["description"] = "x" * 2_001
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(EvalSuiteLoadError):
        EvalSuiteLoader(path).load()


def test_malformed_json_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "malformed.json"
    path.write_text("{not-json", encoding="utf-8")

    with pytest.raises(EvalSuiteLoadError):
        EvalSuiteLoader(path).load()
