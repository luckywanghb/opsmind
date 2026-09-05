# TASK-P1-007 Independent Tester Report

## Verdict

`FAIL`

```text
BLOCKER: 0
MAJOR: 3
MINOR: 0
NIT: 0
```

Reviewer hard gate: **NOT MET** (`MAJOR != 0`).

## Identity and scope

- Role: Independent Tester
- Product commit tested: `720c2882a23e3830b85405625af64bb30e33d568`
- Product implementation commit: `b1dcac2f8184bc80c2f0d19ca4f3d5d789c66324`
- Base: `520c7b6e4bd2767003986644a36c89017463a617`
- PR: #19, Draft, `task/TASK-P1-007-dev` → `main`
- Tester branch: `task/TASK-P1-007-test`
- Product code modified by Tester: no
- Live DeepSeek/browser acceptance: not run, as neither is a TASK-P1-007 gate

The Tester independently read the original task package, `AGENTS.md`,
ADR-002, ADR-003, the architecture/API/development documents, the P1-006 and
P1-007 Developer Reports, and the PR #19 metadata/diff. Developer conclusions
were not treated as test results.

## Findings

### MAJOR-1 — A catchable failure after STARTED but before the current try block leaves a false long-lived STARTED run

Evidence:

- `src/opsmind/api/app.py:391` durably creates `STARTED`.
- `src/opsmind/api/app.py:400-411` builds `IdentityState`/`OpsAgentState` after
  the run exists but outside the failure-finalization `try`.
- The `try` begins only at `src/opsmind/api/app.py:412`.
- The independent fault-injection probe at
  `tests/test_p1_007_independent_adversarial.py:43` raises a normal
  `RuntimeError` during state construction. The API safely returns 500 and
  does not leak the exception sentinel, but the correlated record remains
  `STARTED` with no terminal error instead of becoming `FAILED /`
  `INTERNAL_SERVER_ERROR`.

Impact:

- Violates the required post-creation lifecycle (`STARTED → FAILED` for a
  catchable unexpected failure).
- Produces a stale in-flight audit record without a process crash; ADR-003
  lists process crash, not ordinary catchable harness exceptions, as the
  accepted source of stale STARTED records.

Required remediation:

- Bring every catchable operation after successful `start()`—including state
  construction—inside the failure-finalization boundary.
- Retain the current safe typed error and persistence-failure precedence.

### MAJOR-2 — Run detail reads cross SQLite snapshots during concurrent finalization

Evidence:

- `src/opsmind/runs/sqlite.py:180-195` reads the parent, steps, and evidence in
  three SELECT statements without an explicit read transaction.
- The deterministic barrier probe at
  `tests/test_p1_007_independent_adversarial.py:139` pauses after reading the
  STARTED parent, commits a valid SUCCEEDED finalization, then permits the
  child reads.
- The reader observes the old STARTED parent and new terminal children. The
  valid database is consequently reported as `RunDataIntegrityError`
  (`stored run failed typed validation`), which the HTTP layer would expose as
  a spurious safe 503.

Impact:

- Violates the required basic concurrent-run/read isolation and makes a valid
  atomic writer transaction appear corrupt.
- A future Eval UI or audit client can intermittently fail exactly while a run
  finalizes.

Required remediation:

- Read the parent and both child collections under one explicit SQLite read
  transaction/snapshot (or an equivalent single-snapshot query strategy).
- Preserve typed corruption rejection for genuinely malformed stored data.

### MAJOR-3 — A schema labelled v1 is accepted even when all required integrity constraints are absent

Evidence:

- ADR/task schema requirements include primary keys, foreign keys, unique
  `run_id`/`request_id`, deterministic child ordering, and required indexes.
- `src/opsmind/runs/sqlite.py:364-376` validates only table presence and the set
  of column names. It does not validate PK/NOT NULL attributes, unique indexes,
  foreign keys, CHECK constraints, or the required indexes.
- The independent corruption probe at
  `tests/test_p1_007_independent_adversarial.py:216-251` creates a schema with
  version `1` and exactly the expected column names but no constraints or
  indexes. `SQLiteRunRepository.list()` accepts it instead of raising
  `IncompatibleRunSchemaError`.

Impact:

- A damaged/partial v1 database can silently lose run/request uniqueness,
  referential integrity, and ordered-child guarantees—the core audit
  invariants of this task.
- This contradicts the Developer Report claim that incomplete v1 schemas fail
  explicitly and weakens ID-collision/cross-run protection.

Required remediation:

- Validate the schema invariants that correctness depends on, using SQLite
  metadata such as `PRAGMA table_info`, `index_list`/`index_info`, and
  `foreign_key_list` (plus the lifecycle/status checks if they remain part of
  the v1 contract).
- Add a regression that rejects a version-labelled schema with matching
  columns but missing constraints.

## Independent probes that passed

The same test-only module also independently confirmed:

- malformed typed JSON returns safe `503 RUN_PERSISTENCE_UNAVAILABLE` without
  reflecting the stored sentinel;
- FAILED finalization rolls back the parent transition and step insertion
  together when step insertion fails;
- eight repository instances can race on first use, create/finalize distinct
  runs, and retain isolated IDs/lifecycles.

Static boundary inspection also found no SQLite/SQL/repository import in Agent
graph, Agent nodes, tool harness, or model gateway. Persistence is composed at
the API/runtime boundary. The persistence projection accepts the typed public
response, ordered safe trace, and canonical `EvidenceItem`; provider response
objects and raw tool execution objects are not passed to the store. Direct
SQLite leakage regressions for prompt/provider/tool/traceback sentinels passed
in the product suite.

## P1-006 / safety regression result

- Focused persistence plus P1-006 adversarial, Evidence-Bound, grounded-output,
  and READ_ONLY suites: `89 passed`.
- Full product suite excluding the deliberately failing Tester probes:
  `476 passed, 1 live deselected, 1 existing warning`.
- No prompt, routing, graph-edge, tool-policy, Evidence schema, or grounded
  renderer change was found in the PR. The graph diff is limited to accepting
  the request-local safe-event sink used by the runtime harness.
- Evidence stable IDs/order, malformed evidence fail-closed behavior,
  `not_found`, Unicode `Cf` grounded rendering, and WRITE-tool blocking all
  remain covered and passed.

## Validation evidence

```text
PYTHONPATH=src <shared-python-3.11> -m pytest -q \
  tests/test_p1_007_independent_adversarial.py
→ 3 failed, 3 passed, 1 warning

PYTHONPATH=src <shared-python-3.11> -m pytest -q \
  --ignore=tests/test_p1_007_independent_adversarial.py
→ 476 passed, 1 deselected, 1 warning

PYTHONPATH=src <shared-python-3.11> -m pytest -q \
  tests/test_run_api.py tests/test_run_repository.py \
  tests/test_p1_006_independent_adversarial.py \
  tests/test_grounded_response_contract.py tests/test_tool_loop.py
→ 89 passed, 1 warning

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

The shared Python 3.11 environment was used only as an installed dependency
environment; `PYTHONPATH=src` loaded product/test code from the independent
Tester worktree.

## Gate decision

Do not advance PR #19 to Reviewer yet. Remediate all three MAJOR findings and
rerun the independent probes. The Reviewer hard gate requires BLOCKER=0 and
MAJOR=0.
