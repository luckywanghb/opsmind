# TASK-P1-007 Developer Remediation Final Follow-up Report

## Identity

- Task: TASK-P1-007 / GitHub Issue #18
- Role: Developer remediation follow-up
- Branch: `task/TASK-P1-007-dev`
- Reviewer remediation Tester report: `tasks/review/TASK-P1-007-review-remediation-tester-report.md`
- All historical Tester and Reviewer reports remain unchanged.

## Findings addressed

### Complete CHECK semantics (MAJOR)

`_validate_table_checks()` now parses the table DDL only as a tokenized
structure: SQL comments and quoted literals are skipped, real CHECK expression
parentheses are extracted, and the exact version-1 lifecycle, sequence, and
step-status expressions are required. Weak alternatives such as `<> 'INVALID'`
or `<> -1` cannot match the canonical allowed-set/range expressions.

The existing SAVEPOINT probes remain as executable defense-in-depth checks and
now exercise multiple invalid values (`INVALID`/`OTHER_INVALID`, `-1`/`-2`,
and two invalid statuses). Each probe is rolled back and released, so schema
validation does not leave rows behind. Regression tests cover fake CHECK text
in comments/strings, weak CHECK expressions, and direct rejection of invalid
lifecycle, sequence, and status values.

### Concurrent WAL initialization (MAJOR)

A process-wide initialization lock now serializes WAL-mode establishment and
the schema transaction across separate `SQLiteRunRepository` instances. The
existing connection busy timeout remains in force. A repeated deterministic
pressure regression creates 20 fresh databases and initializes eight separate
repositories concurrently per database, covering the first-use WAL transition.

### Documentation

The persistence README correction from the prior remediation is retained,
including both run-query endpoints and the explicit lack of conversation
checkpoint/restoration support. No Reviewer report was modified.

No graph topology, business reasoning, Evidence semantics, frontend behavior,
or dependency file changed.

## Verification

```text
pytest -q tests/test_p1_007_schema_check_strict.py \
  tests/test_p1_007_schema_checks.py
→ 4 passed

pytest -q tests/test_p1_007_schema_check_strict.py \
  tests/test_p1_007_schema_checks.py \
  tests/test_p1_007_independent_adversarial.py \
  tests/test_p1_007_remediation_adversarial.py
→ 11 passed, 1 warning

pytest -q
→ 487 passed, 1 deselected, 1 warning

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
