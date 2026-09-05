# TASK-P1-007 Independent Remediation Tester Report

## Verdict

`FAIL`

```text
BLOCKER: 0
MAJOR: 1
MINOR: 0
NIT: 0
```

Reviewer hard gate: **NOT MET** (`MAJOR != 0`).

## Identity

- Role: Independent remediation Tester
- Developer remediation commit tested: `5942f0c99892f62a66d427649a41f3a6a1a98ec8`
- PR: #19, `task/TASK-P1-007-dev` → `main`
- Tester branch: `task/TASK-P1-007-test`
- Original FAIL report: `tasks/review/TASK-P1-007-tester-report.md`
  (retained unchanged)
- Product code modified by Tester: no
- New Tester-only strict probe:
  `tests/test_p1_007_remediation_adversarial.py`

The remediation patch was cherry-picked into the independent test branch as
`78a6d45`; the product source tree is identical to Developer commit `5942f0c`.

## Original finding retest

### MAJOR-1 — Post-STARTED exception lifecycle: CLOSED

`IdentityState`/`OpsAgentState` construction now occurs inside the existing
post-start `try` boundary. The original injected state-construction failure is
persisted as `FAILED / INTERNAL_SERVER_ERROR`; the exception sentinel is not
returned or persisted.

Original probe result: `PASS`.

### MAJOR-2 — Concurrent detail read snapshot: CLOSED

`SQLiteRunRepository.get()` now starts one explicit read transaction before
reading the parent and children. WAL mode allows the deterministic writer to
commit while that snapshot remains active. The probe observes a coherent
STARTED snapshot rather than mixed parent/children or a false integrity error.

Original probe result: `PASS`.

### MAJOR-3 — Version-1 schema integrity validation: NOT FULLY CLOSED

The original constraintless-schema probe now passes, and the remediation
validates substantially more v1 metadata. However, the global uniqueness
invariant still has an acceptance hole.

`PRAGMA index_list` reports whether an index is partial. At
`src/opsmind/runs/sqlite.py:521-530`, `_index_definitions()` records only the
index name, unique flag, and indexed columns; it drops the `partial` flag. At
`src/opsmind/runs/sqlite.py:492-495`, any unique index over the expected columns
is therefore accepted as the required uniqueness constraint.

The strict probe creates an otherwise valid v1 schema with:

```sql
CREATE UNIQUE INDEX partial_request_id_uniqueness
ON agent_runs(request_id)
WHERE request_id <> 'UNPROTECTED';
```

and an equivalent partial evidence-ID index. These indexes do not enforce
global uniqueness: excluded request/evidence IDs may be duplicated. The
repository nevertheless accepts the schema instead of raising
`IncompatibleRunSchemaError`.

Impact:

- `request_id` uniqueness and `(run_id, evidence_id)` uniqueness remain
  bypassable in a damaged/partial schema labelled v1.
- These are core audit and cross-run identity invariants, not optional query
  optimizations.
- The same omitted metadata also lets a partial named index satisfy the
  required discovery-index check.

Required remediation:

- Include SQLite's `partial` metadata in index definitions.
- Require non-partial indexes for every global UNIQUE and required named-index
  invariant.
- Retain the new PK, FK, NOT NULL, CHECK, and exact-column validation.
- Add the strict partial-index probe as a product regression.

## Validation evidence

```text
PYTHONPATH=src <shared-python-3.11> -m pytest -q \
  tests/test_p1_007_independent_adversarial.py
→ 6 passed, 1 warning

PYTHONPATH=src <shared-python-3.11> -m pytest -q \
  tests/test_p1_007_remediation_adversarial.py
→ 1 failed
   test_partial_unique_indexes_do_not_satisfy_global_uniqueness

PYTHONPATH=src <shared-python-3.11> -m pytest -q \
  --ignore=tests/test_p1_007_remediation_adversarial.py
→ 482 passed, 1 live deselected, 1 warning

PYTHONPATH=src <shared-python-3.11> -m pytest -q \
  tests/test_p1_007_independent_adversarial.py \
  tests/test_run_api.py tests/test_run_repository.py \
  tests/test_p1_006_independent_adversarial.py \
  tests/test_grounded_response_contract.py tests/test_tool_loop.py
→ 95 passed, 1 warning

PYTHONPATH=src <shared-python-3.11> -m ruff check .
→ PASS

PYTHONPATH=src <shared-python-3.11> -m mypy src
→ Success: no issues found in 42 source files

UV_CACHE_DIR=/private/tmp/opsmind-p1-007-test-uv uv lock --check --offline
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

The focused/full regressions continue to cover transaction rollback, malformed
JSON safe 503 behavior, IDs, 404s, persistence failures, raw
provider/tool/prompt/traceback leakage, canonical Evidence, Unicode `Cf`,
`not_found`, grounded output, and READ_ONLY enforcement. No new regression was
observed outside the remaining schema-validation MAJOR.

## Gate decision

Do not advance PR #19 to Sol Medium Reviewer. MAJOR-1 and MAJOR-2 are closed;
MAJOR-3 requires one further narrow schema-index remediation and independent
retest. The Reviewer gate requires BLOCKER=0 and MAJOR=0.
