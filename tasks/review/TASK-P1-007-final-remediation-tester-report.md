# TASK-P1-007 Final Remediation Independent Tester Report

## Verdict

`PASS`

```text
BLOCKER: 0
MAJOR: 0
MINOR: 0
NIT: 0
```

Reviewer re-entry gate: **MET** (`BLOCKER = 0`, `MAJOR = 0`).

## Identity

- Role: Independent Tester after final remediation
- Product commit tested: `426539a8e6559da1990ca230bc5cf0c53d44ffa3`
- PR: #19, `task/TASK-P1-007-dev` → `main`
- Tester branch: `task/TASK-P1-007-test`
- Product patch on Tester branch: `b173a1f` (cherry-pick of `426539a`)
- Prior Tester reports, including both FAIL reports: retained unchanged
- Product code authored or modified by Tester: no
- Independent strict probe retained:
  `tests/test_p1_007_schema_check_strict.py`

The product source, frontend, README, and dependency files in the independent
worktree match Developer commit `426539a`.

## Previous MAJOR retest

### Complete CHECK semantics: CLOSED

The version-1 validator now extracts real table-level CHECK expressions from
`sqlite_master.sql`, ignoring SQL comments and quoted text, normalizes them,
and requires the exact canonical expression set for every table. It retains
transactional SAVEPOINT probes and exercises multiple invalid values.

Independent evidence:

- The historical constraintless-v1 and CHECK-looking-comment/string schemas
  are rejected safely.
- The strict weak-CHECK schema using `<> 'INVALID'`, `<> -1`, and
  `<> 'invalid'` is rejected during initialization.
- Canonical v1 constraints reject both tested invalid lifecycle/status values
  and negative child sequences.
- Schema validation probes roll back and leave no probe rows or partial state.
- Malformed/incompatible schemas fail closed without leaking database details.

The earlier finding that a single rejected sample could bless a weak schema is
no longer reproducible.

### Concurrent first initialization: CLOSED

Initialization of separate repository objects is now serialized across the
process before the WAL transition and schema transaction. The independent
historical first-use probe and the new repeated pressure regression pass.

Pressure evidence:

```text
20 fresh SQLite databases × 8 separate repository instances
→ 160 concurrent first-initialization results completed successfully
→ no `database is locked`, partial schema, duplicate ID, or cross-run row
```

The previous nondeterministic `PRAGMA journal_mode = WAL` lock failure was not
reproduced after the remediation.

## Historical adversarial coverage

All retained independent probes pass, covering:

- STARTED/SUCCEEDED/FAILED lifecycle and atomic terminal finalization;
- transaction rollback and no partial child/snapshot persistence;
- request/run/thread identity separation, collisions, and cross-run isolation;
- unique constraints including rejection of partial-index substitutes;
- concurrent reads and concurrent first use across repository instances;
- canonical compact Evidence and safe trace persistence;
- raw provider/tool payload, prompt, arbitrary context, secret, path, exception,
  and traceback non-persistence/non-disclosure;
- malformed JSON, schema corruption, unsupported schema, 404, and persistence
  failure behavior;
- P1-006 state, Evidence, grounded-output, tool-loop, Unicode `Cf`,
  `not_found`, API-boundary, and READ_ONLY invariants.

No graph topology, business reasoning, tool policy, Evidence contract,
frontend behavior, or dependency regression was observed.

## Validation evidence

```text
PYTHONPATH=src <shared-python-3.11> -m pytest -q \
  tests/test_p1_007_independent_adversarial.py \
  tests/test_p1_007_remediation_adversarial.py \
  tests/test_p1_007_schema_checks.py \
  tests/test_p1_007_schema_check_strict.py
→ 11 passed, 1 warning

PYTHONPATH=src <shared-python-3.11> -m pytest -q \
  tests/test_p1_007_schema_checks.py::\
test_separate_repositories_serialize_first_initialization \
  tests/test_p1_007_independent_adversarial.py::\
test_concurrent_first_use_across_repository_instances_is_isolated
→ 2 passed, 1 warning
→ first test performs the required 20 × 8 pressure run

Focused persistence/P1-006/Evidence/READ_ONLY regression
→ 310 passed, 1 warning

PYTHONPATH=src <shared-python-3.11> -m pytest -q
→ 487 passed, 1 deselected, 1 warning

PYTHONPATH=src <shared-python-3.11> -m ruff check .
→ PASS

PYTHONPATH=src <shared-python-3.11> -m mypy src
→ Success: no issues found in 42 source files

UV_CACHE_DIR=/private/tmp/opsmind-p1-007-final-uv uv lock --check --offline
→ Resolved 55 packages; PASS

git diff --check
→ PASS

git diff --exit-code 426539a -- src web README.md pyproject.toml uv.lock
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

The single warning is the pre-existing Starlette `TestClient`/`httpx`
deprecation warning and is unrelated to TASK-P1-007 behavior. The deselected
test is the opt-in live model test selected out by repository pytest policy.

## Gate decision

PR #19 may return to the Sol Medium Reviewer. Both previously open MAJOR
findings are closed and the required hard gate is satisfied:

```text
BLOCKER = 0
MAJOR = 0
```
