# TASK-P1-008 — Developer Remediation Report

## Identity

- Task: `TASK-P1-008`
- Role: `Developer Remediation`
- Branch: `task/TASK-P1-008-dev`
- Tester report: `tasks/review/TASK-P1-008-tester-report.md`
- Scope: remediation of the six reported MAJOR findings only
- Merge/push: `PROHIBITED`

The original independent Tester report remains unchanged. This report records
the product remediation and local verification for a subsequent independent
retest.

## Remediated findings

### MAJOR-1 — JSON equality type strictness

Added recursive JSON-value comparison with exact runtime JSON types, so boolean
and numeric values cannot compare equal through Python's `bool == int` rule.
Nested lists and objects use the same strict comparison. The intentional
substring behavior of `evidence_field_contains` remains unchanged for strings;
list membership now uses the strict JSON comparison.

### MAJOR-2 — Canonical terminal status

Evaluation observations expose a canonical `TaskStatus` conversion boundary,
and evaluator dispatch validates every observation before invoking an
evaluator. A corrupt terminal status therefore produces a safe assertion
`ERROR` instead of matching a fabricated value.

### MAJOR-3 — Evaluator-specific suite validation

`EvaluatorRegistry.validate_assertion` now validates evaluator-owned
expectation shapes during suite loading: allowed enum values, boolean and
non-negative integer scalars, non-empty string lists, required object keys,
object key allowlists, and non-empty string fields. The loader also rejects
any assertion `turn_index` outside `0 <= turn_index < len(case.turns)`.

### MAJOR-4 — Bounded nesting and loader normalization

Eval JSON validation now uses an explicit work list with a finite nesting
limit. The loader performs a suite-wide depth check before Pydantic validation
and normalizes decoder, validation, and recursion failures to
`EvalSuiteLoadError` (`EVAL_SUITE_INVALID` at the API boundary). Field-specific
size limits remain in force.

### MAJOR-5 — Run-reference fail-closed behavior

`EvalPersistenceService.complete` no longer skips verification when a run
repository is absent. Any case containing run IDs now fails with a safe
`Agent run reference` persistence error; configured repositories continue to
verify every run ID before terminal eval commit.

### MAJOR-6 — Completion persistence failure lifecycle

When terminal completed-job persistence fails after a durable `STARTED` row,
`EvalRunner` makes one safe `FAILED` finalization attempt using the normalized
code `EVAL_PERSISTENCE_FAILED`. If that fallback also fails, a sanitized eval
persistence error is raised with the original completion failure preserved as
the cause, without crossing raw fallback/provider text into the public error
boundary.

## Scope guard

Changes are limited to the eval models, loader, evaluators, persistence,
runner, and review reports. Graph topology, prompts, model routing, tools,
Evidence semantics, grounded rendering, `READ_ONLY` policy, frontend code,
Run schema v1, and existing API semantics were not changed.

## Verification

All commands ran in `/Users/hongbo/vscode/agent/opsmind-p1-008` using the
existing shared Python environment:

```text
../opsmind-p1-007/.venv/bin/python -m pytest -q \
  tests/test_p1_008_independent_adversarial.py
→ 17 passed, 1 warning

../opsmind-p1-007/.venv/bin/python -m pytest
→ 554 passed, 1 deselected, 1 warning

../opsmind-p1-007/.venv/bin/python -m ruff check .
→ PASS

../opsmind-p1-007/.venv/bin/python -m mypy src
→ Success: no issues found in 51 source files

git diff --check
→ PASS
```

The single warning is the pre-existing Starlette `TestClient`/`httpx`
deprecation warning. No network access, `uv`, push, or merge was used.

## Handoff

The six Tester MAJOR findings are remediated locally. The unchanged Tester
report remains the independent record; the branch is ready for independent
retest and Reviewer re-entry consideration, subject to the PM Architecture
Gate.
