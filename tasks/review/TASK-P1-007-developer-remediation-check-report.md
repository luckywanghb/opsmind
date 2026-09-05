# TASK-P1-007 Developer Remediation CHECK/README Follow-up Report

## Identity

- Task: TASK-P1-007 / GitHub Issue #18
- Role: Developer remediation follow-up
- Branch: `task/TASK-P1-007-dev`
- Reviewer findings addressed: CHECK validation MAJOR and README persistence MINOR
- Reviewer report: not modified

## Remediation

### Executable v1 CHECK validation

`_validate_table_checks()` no longer treats `sqlite_master.sql` text as proof
that a CHECK exists. SQLite does not provide a CHECK-specific PRAGMA, so the
validator now executes deliberately invalid lifecycle, sequence, and step
status inserts inside per-table SAVEPOINTs. A successful invalid insert raises
`IncompatibleRunSchemaError`; a constraint rejection proves the invariant is
active. Every SAVEPOINT is rolled back and released, leaving schema
initialization data unchanged. This also prevents comments or string literals
containing CHECK-looking text from bypassing validation.

Added regression coverage verifies both that fake CHECK text is rejected and
that the real schema rejects invalid lifecycle values, negative child
sequences, and invalid step statuses.

### README persistence contract

The contradictory statement that persistence was absent was corrected. README
now states that validated runs are persisted and lists:

- `GET /api/v1/runs`
- `GET /api/v1/runs/{run_id}`

It explicitly states that conversation checkpoints/restoration and memory are
not supported.

No Reviewer report was changed, and no graph topology, business reasoning,
Evidence semantics, frontend behavior, or dependency file was changed.

## Verification

```text
pytest -q tests/test_p1_007_schema_checks.py
→ 2 passed

pytest -q tests/test_p1_007_independent_adversarial.py \
  tests/test_p1_007_remediation_adversarial.py \
  tests/test_p1_007_schema_checks.py
→ 9 passed, 1 warning

pytest -q
→ 485 passed, 1 deselected, 1 warning

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

The remediation is committed on the current branch and has not been pushed.
