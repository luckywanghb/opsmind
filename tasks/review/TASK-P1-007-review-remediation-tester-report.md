# TASK-P1-007 Reviewer Remediation Independent Tester Report

## Verdict

`FAIL`

```text
BLOCKER: 0
MAJOR: 2
MINOR: 0
NIT: 0
```

Reviewer re-entry gate: **NOT MET** (`MAJOR != 0`).

## Identity

- Role: Independent Tester after Reviewer remediation
- Product commit tested: `3fb9e5c3128d87141fcca8a894a44921542e1092`
- PR: #19, `task/TASK-P1-007-dev` → `main`
- Tester branch: `task/TASK-P1-007-test`
- Product patch on Tester branch: `a839b9d` (cherry-pick of `3fb9e5c`)
- Historical Tester reports and probes: retained unchanged
- Product code authored or modified by Tester: no
- New Tester-only probe: `tests/test_p1_007_schema_check_strict.py`

The product source/frontend/dependency tree in the independent worktree matches
Developer commit `3fb9e5c`.

## Reviewer finding retest

### Reviewer MINOR — README persistence contract: CLOSED

README now documents durable validated runs, both run-query endpoints, the
configurable store path, and the explicit absence of conversation checkpoint,
restoration, and memory behavior. The previous contradictory statement that
persistence was absent has been removed.

### Reviewer MAJOR — Executable v1 CHECK validation: NOT CLOSED

The new product tests correctly reject CHECK-looking comments/string literals
and confirm that the canonical schema rejects the sampled invalid values.
However, schema validation equates rejection of one fixed sample with proof of
the complete required constraint.

Evidence:

- `src/opsmind/runs/sqlite.py:456-475` tests only lifecycle value `INVALID` and
  accepts any `sqlite3.IntegrityError` as proof of the required three-value
  lifecycle domain.
- `src/opsmind/runs/sqlite.py:498-521` tests only sequence `-1` and status
  `invalid`.
- `src/opsmind/runs/sqlite.py:525-534` tests only evidence sequence `-1`.
- The strict probe creates an otherwise valid v1 schema with weak checks such
  as `lifecycle_status <> 'INVALID'`, `sequence <> -1`, and
  `status <> 'invalid'`. It passes initialization, after which
  `OTHER_INVALID`, sequence `-2`, and another invalid status are successfully
  inserted.

Impact:

- A partial/damaged v1 schema can still be treated as authoritative while not
  enforcing the documented lifecycle, ordering, and step-status domains.
- Catching any integrity error also cannot establish that the target CHECK,
  rather than another constraint, caused rejection.

Required remediation:

- Validate the complete versioned CHECK semantics rather than a single
  negative sample. A canonical schema fingerprint/DDL contract or an
  equivalently strong deterministic approach is appropriate; single-value
  probing is insufficient.
- Preserve savepoint rollback and safe incompatible-schema failure behavior.
- Promote the strict weak-CHECK probe into product regression coverage.

## Additional MAJOR — Concurrent first initialization can fail at WAL setup

`src/opsmind/runs/sqlite.py:332` executes `PRAGMA journal_mode = WAL` before
the transaction that serializes schema initialization. With multiple
repository instances opening the same new database, concurrent PRAGMA calls
can raise `sqlite3.OperationalError: database is locked`; the configured busy
timeout did not prevent this failure.

Evidence:

- The historical eight-repository first-use probe failed once during the
  combined schema/history run.
- A separate sequential stress attempt reproduced the same failure on
  iteration 9 of 20 and stopped immediately.
- The same test also passes in other runs, confirming a real race rather than
  a deterministic fixture error.

Impact:

- Violates the task's concurrent-safe initialization requirement.
- A valid simultaneous chat/app initialization can fail closed with 503 even
  though the database and requests are otherwise valid.

Required remediation:

- Serialize or bounded-retry WAL mode establishment across repository
  instances/processes before declaring initialization complete.
- Add repeated concurrent-first-use coverage that reliably exercises the WAL
  transition, not only writes after one repository has initialized the file.

## Validation evidence

```text
PYTHONPATH=src <shared-python-3.11> -m pytest -q \
  tests/test_p1_007_independent_adversarial.py \
  tests/test_p1_007_remediation_adversarial.py \
  tests/test_p1_007_schema_checks.py
→ 8 passed, 1 failed, 1 warning
  failure: concurrent first-use `PRAGMA journal_mode = WAL`: database is locked

Repeat the concurrent-first-use test up to 20 times
→ iterations 1-8 passed; iteration 9 failed with the same lock error

PYTHONPATH=src <shared-python-3.11> -m pytest -q \
  tests/test_p1_007_schema_check_strict.py
→ 1 failed
  weak CHECK constraints were accepted and alternate invalid values inserted

PYTHONPATH=src <shared-python-3.11> -m pytest -q \
  --ignore=tests/test_p1_007_schema_check_strict.py
→ 485 passed, 1 live deselected, 1 warning
  (the flaky concurrent-first-use probe passed in this invocation)

PYTHONPATH=src <shared-python-3.11> -m pytest -q
→ 485 passed, 1 failed, 1 live deselected, 1 warning
  failure: strict weak-CHECK probe

Focused persistence/P1-006/Evidence/READ_ONLY regression
→ 98 passed, 1 warning

PYTHONPATH=src <shared-python-3.11> -m pytest -q \
  tests/test_p1_007_schema_checks.py
→ 2 passed

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

All other historical lifecycle, snapshot, partial-index, rollback, ID,
malformed-JSON, 404, persistence-failure, leakage, canonical Evidence,
Unicode `Cf`, `not_found`, grounded-output, and READ_ONLY probes remain green
when the nondeterministic initialization race does not fire.

## Gate decision

Do not return PR #19 to Reviewer. The README MINOR is closed, but the Reviewer
CHECK MAJOR is not completely remediated and a reproducible SQLite
initialization-concurrency MAJOR remains. Required gate:

```text
BLOCKER = 0
MAJOR = 0
```
