# TASK-P1-007 Developer Remediation Follow-up Report

## Identity

- Task: TASK-P1-007 / GitHub Issue #18
- Role: Developer remediation follow-up
- Branch: `task/TASK-P1-007-dev`
- Independent remediation Tester report: `tasks/review/TASK-P1-007-remediation-tester-report.md`
- Original Tester report remains retained unchanged.

## Follow-up finding

The independent remediation probe found that `_index_definitions()` discarded
the `partial` column reported by `PRAGMA index_list`. Consequently, a partial
UNIQUE index could be mistaken for the required global uniqueness constraint.

The index metadata now carries the partial flag. Schema validation requires
`partial = 0` for both required global UNIQUE constraints (`request_id` and
`(run_id, evidence_id)`) and all required named discovery indexes. Partial
indexes therefore cannot satisfy any v1 invariant.

No graph, runtime reasoning, Evidence semantics, frontend code, or dependency
file was changed.

## Verification

```text
pytest -q tests/test_p1_007_remediation_adversarial.py
→ 1 passed

pytest -q
→ 483 passed, 1 deselected, 1 warning

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

The follow-up fix is committed on the current branch and has not been pushed.
