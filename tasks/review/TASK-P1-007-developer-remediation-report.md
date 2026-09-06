# TASK-P1-007 Developer Remediation Report

## Identity

- Task: TASK-P1-007 / GitHub Issue #18
- Role: Developer remediation
- Branch: `task/TASK-P1-007-dev`
- Original Tester report: `tasks/review/TASK-P1-007-tester-report.md`
- Scope: remediation of the three reported MAJOR findings only

The original Tester report and its FAIL evidence are retained unchanged. This
report records the remediation and its verification; it does not replace the
independent Tester record.

## Remediated findings

### MAJOR-1: post-STARTED state construction failure

State construction now runs inside the existing failure-finalization boundary,
alongside runtime execution and safe response projection. A catchable error
after `create_started` therefore goes through `RunPersistenceService.fail`,
retaining the normalized error code, safe failure-step projection, and existing
persistence-error precedence. Initial `start()` failures remain pre-run and do
not claim a run ID.

### MAJOR-2: inconsistent SQLite detail reads

`SQLiteRunRepository.get()` now opens one explicit read transaction before the
parent SELECT and reads the parent, ordered steps, and ordered evidence from
that same SQLite snapshot before committing. SQLite WAL mode is enabled during
schema initialization so a terminal writer can commit while a reader holds its
consistent snapshot. Typed validation and corruption rejection are unchanged.

### MAJOR-3: hollow schema labelled v1

Version-1 validation now checks the metadata reported by SQLite for:

- exact table columns and required NOT NULL attributes;
- all required primary keys;
- unique `agent_runs.request_id` and
  `evidence_records(run_id, evidence_id)` constraints;
- child-to-parent foreign keys with `ON DELETE CASCADE`;
- lifecycle, step-status, and non-negative sequence CHECK constraints; and
- the required named indexes and their indexed columns.

A schema with only the version label and matching column names is rejected with
`IncompatibleRunSchemaError`. The newly-created schema explicitly marks the
metadata key and run ID primary keys NOT NULL.

## Files changed

- `src/opsmind/api/app.py`
- `src/opsmind/runs/sqlite.py`

No graph topology, business reasoning, Evidence semantics, provider/model
contracts, frontend code, dependency files, or unrelated scope was changed.

## Verification

Using the shared Python 3.11 environment with `PYTHONPATH=src`:

```text
pytest -q tests/test_p1_007_independent_adversarial.py
→ 6 passed, 1 warning

pytest -q --ignore=tests/test_p1_007_independent_adversarial.py
→ 476 passed, 1 deselected, 1 warning

pytest -q
→ 482 passed, 1 deselected, 1 warning

ruff check .
→ PASS

mypy src
→ Success: no issues found in 42 source files

uv lock --check --offline
→ Resolved 55 packages; PASS

git diff --check
→ PASS

git diff --exit-code -- uv.lock web/package-lock.json
→ PASS

cd web && npm test -- --run
→ 4 files passed; 22 tests passed

cd web && npm run lint
→ PASS

cd web && npm run build
→ PASS
```

The remediation is committed on the current branch. It has not been pushed.
