# TASK-P1-008 Independent Tester Report

## Decision — independent re-test

`PASS`

```text
BLOCKER: 0
MAJOR: 0
MINOR: 0
NIT: 0
```

Reviewer Entry Gate: **MET** (`BLOCKER = 0`, `MAJOR = 0`).

This current decision supersedes the initial pre-remediation decision recorded
below. All 17 retained independent adversarial probes pass on remediation HEAD
`890f709`; no new Tester finding was identified.

## Identity and scope

- Role: Independent Tester / adversarial regression pass
- Baseline product commit (initial test): `005e489740ce00f1f5d366323b1ad48e141a6e11`
- Initial implementation commit: `0b01dda`
- Re-test product commit: `890f709b4ad72f2cabf8a53b8b04486e1a9c69bd`
- Base main: `e0e0675d6c638401d91643aa546bb106b3188dca`
- Tester branch: `task/TASK-P1-008-test`
- Product source/frontend/dependency files modified by Tester: no
- Tester-only additions: `tests/test_p1_008_independent_adversarial.py` and this report

The probes were written independently of the Developer-authored eval tests.
No prompt, tool, RAG, conversation, or frontend product behavior was changed.

## Initial findings (pre-remediation)

### MAJOR-1 — JSON equality is not type-strict

`tool_argument_equals` and `evidence_field_equals` use Python `==` at
`src/opsmind/evals/evaluators.py:316` and `src/opsmind/evals/evaluators.py:427`.
The independent probe presents an actual JSON boolean `false` and expects the
JSON number `0`; both assertions incorrectly return `PASS` because Python
considers `False == 0`.

Evidence: `tests/test_p1_008_independent_adversarial.py:220-266`.

Impact: A Golden assertion can pass for a value of the wrong JSON type,
undermining deterministic evaluator results and allowing semantically wrong
tool arguments or evidence to be treated as correct.

Required remediation: compare JSON values with both type and value semantics
(while preserving the intentional substring behavior of `contains`), and add
regression coverage for boolean/number and other cross-type pairs.

### MAJOR-2 — Invalid terminal status is accepted as a valid observation

`EvaluationObservation.terminal_status` is an unconstrained `str` at
`src/opsmind/evals/models.py:120-132`; the contract's `TaskStatus` values are
defined in `src/opsmind/state.py:149-158`. The probe constructs
`NOT_A_TASK_STATUS`, then expects that same invalid value. The terminal-status
evaluator returns `PASS` instead of `ERROR`.

Evidence: `tests/test_p1_008_independent_adversarial.py:269-282`.

Impact: Invalid or fabricated execution observations can satisfy enum-based
Golden assertions. This weakens the typed safe-observation boundary and can
hide runtime contract corruption.

Required remediation: type or validate terminal status against the canonical
`TaskStatus` domain before evaluator dispatch; invalid observations must fail
closed as evaluator `ERROR`.

### MAJOR-3 — Loader accepts malformed evaluator expectations

`src/opsmind/evals/loader.py:64-82` checks only Pydantic shape and whether an
evaluator name is registered. It does not validate evaluator-specific
expectation shapes or cross-check `turn_index` against the case's turn count.
The independent probes show that all of these malformed assertions load:

- `tool_argument_equals` without a required `field`/`value`;
- `intent_in` with an object instead of a list of enum values;
- `reply_nonempty` with `turn_index=1` on a one-turn case.

Evidence: `tests/test_p1_008_independent_adversarial.py:383-412`.

Impact: Invalid suites are accepted and only fail later, or can be interpreted
in a way that is not what the suite author specified. This violates the strict
Golden Suite loader requirement and makes case quality dependent on evaluator
runtime behavior.

Required remediation: add typed/per-evaluator expectation validation during
load, including allowed enum values, required object keys, scalar types, and
`0 <= turn_index < len(turns)`.

### MAJOR-4 — Deeply nested suite input escapes typed loader/API errors

`src/opsmind/evals/models.py:37-55` bounds collection sizes and string lengths
but does not bound nesting depth. `src/opsmind/evals/loader.py:56-61` catches
JSON syntax/type errors but not `RecursionError`. A 1,200-level JSON object,
well below the 512 KiB suite limit, therefore raises raw `RecursionError` from
the loader. Through `POST /api/v1/evals/run`, the same input produces generic
500 `INTERNAL_SERVER_ERROR` instead of the registered 422
`EVAL_SUITE_INVALID` envelope at `src/opsmind/api/app.py:273-284`.

Evidence:

- Direct loader probe: `tests/test_p1_008_independent_adversarial.py:341-352`.
- API normalization probe: `tests/test_p1_008_independent_adversarial.py:355-380`.
- The API log identifies `RecursionError` at the generic handler.

Impact: Attacker-controlled or corrupted suite content can escape the typed
validation boundary and produce an incorrect API error class. It also leaves
the claimed bounded-input contract incomplete.

Required remediation: enforce a finite nesting-depth limit during decoding or
validation, catch decoder recursion failures, and normalize them to
`EvalSuiteLoadError` / `EVAL_SUITE_INVALID`.

### MAJOR-5 — Canonical persistence service permits fabricated run links

`EvalPersistenceService` accepts an optional `run_repository` at
`src/opsmind/evals/persistence.py:42-55` and skips run-reference validation at
`src/opsmind/evals/persistence.py:99-101` when it is omitted. The independent
probe starts a job with no run repository and successfully completes a case
whose `run_ids` contains fabricated `run-1`.

Evidence: `tests/test_p1_008_independent_adversarial.py:415-437`.

Impact: `eval_case_runs` can claim a relationship to an AgentRun that does not
exist. This violates the required real-run referential-integrity invariant and
is especially risky because the exposed service constructor makes the
fail-open path easy to invoke.

Required remediation: make the canonical run repository dependency mandatory,
or fail closed whenever a case includes run IDs and no verifier is available;
verify every relation against the same real `RunRepository` before commit.

### MAJOR-6 — Terminal eval persistence failure leaves durable `STARTED`

`EvalRunner.run_suite` re-raises `EvalPersistenceError` at
`src/opsmind/evals/runner.py:67-79` without attempting the available
`persistence.fail(...)` transition. The independent repository double fails
only `finalize_completed` and permits `finalize_failed`; after the runner
raises, the stored job remains `STARTED` rather than becoming `FAILED`.

Evidence: `tests/test_p1_008_independent_adversarial.py:440-506`.

Impact: A fatal terminal persistence outage leaves an orphaned in-progress eval
job, violating the required separate job lifecycle semantics and making
operational status misleading.

Required remediation: on terminal completion failure, attempt a safe
`FAILED` finalization with a normalized eval persistence error code, preserving
the original failure and avoiding raw provider/tool text. Add a regression
test for both successful failure-finalization and failure of that fallback.

## Passing coverage

The independent suite also passes the following adversarial behaviors:

- concurrent eval jobs remain isolated in one SQLite store;
- C12-style turns share a thread but rotate request/run IDs and do not inject
  the previous prompt;
- `known_gap` does not turn a blocking assertion failure into `PASS`;
- model/provider failures become case `ERROR` with safe codes and no raw
  provider/traceback sentinel;
- malformed read-only tool results are normalized without persisting raw tool
  payloads;
- eval terminal/child-row writes roll back together on child failure;
- malformed stored eval JSON fails with a safe integrity error;
- adding the eval schema preserves existing Run schema v1 and Run reads.

## Initial validation evidence (pre-remediation)

```text
../opsmind-p1-007/.venv/bin/python -m pytest
→ 545 passed, 9 failed, 1 deselected, 1 warning
  The 9 failures are the independent probes above; the existing regression
  tests remain green in this combined run.

../opsmind-p1-007/.venv/bin/python -m pytest \
  --ignore=tests/test_p1_008_independent_adversarial.py
→ 537 passed, 1 deselected, 1 warning

../opsmind-p1-007/.venv/bin/python -m pytest \
  tests/test_p1_008_independent_adversarial.py -q
→ 8 passed, 9 failed, 1 warning

../opsmind-p1-007/.venv/bin/ruff check .
→ PASS

../opsmind-p1-007/.venv/bin/mypy src
→ Success: no issues found in 51 source files

UV_CACHE_DIR=/private/tmp/opsmind-p1-008-test-uv uv lock --check
→ Resolved 55 packages; PASS

git diff --check
→ PASS for tracked changes; staged check is repeated before commit

cd web && npm test
→ 4 files passed; 22 tests passed

cd web && npm run lint
→ PASS

cd web && npm run build
→ PASS

Deterministic mock Golden Suite API smoke sweep
→ HTTP 200; job COMPLETED; 8 cases; 0 PASS, 8 FAIL, 0 ERROR
  This is expected for the intentionally non-semantic deterministic mock and
  is not evidence of live model quality.

DEEPSEEK_API_KEY
→ absent; LIVE_EVAL_NOT_RUN
```

## Initial gate decision (pre-remediation)

Do not return TASK-P1-008 to Reviewer. The Reviewer Entry Gate requires
`BLOCKER = 0` and `MAJOR = 0`; six independent MAJOR findings remain.

PM Architecture Gate: **PENDING** per `docs/adr/ADR-004-eval-runtime.md`.
Merge/push: **PROHIBITED** for this Tester task.

## Re-test at remediation HEAD

### Re-test scope and result

The independent Tester re-ran the original 17 probes without relying on the
Developer's reported result. All 17 passed. The six initial MAJOR findings are
closed as follows.

| Initial finding | Independent closure evidence |
| --- | --- |
| MAJOR-1 — JSON equality type strictness | Boolean `false` no longer satisfies numeric `0` for tool arguments or evidence; the retained probe passes. The fixed comparison is at `src/opsmind/evals/evaluators.py:67-85`, with call sites at `:365` and `:479-480`. |
| MAJOR-2 — Invalid terminal status | A fabricated `NOT_A_TASK_STATUS` observation now yields evaluator `ERROR`; the retained probe passes. Canonical conversion/validation is at `src/opsmind/evals/models.py:182-209` and `src/opsmind/evals/evaluators.py:731-738`. |
| MAJOR-3 — Invalid evaluator expectations | Missing required keys, wrong expectation shape, and out-of-range `turn_index` are rejected during load; all three parametrized probes pass. Validation is at `src/opsmind/evals/loader.py:89-115` and `src/opsmind/evals/evaluators.py:615-718`. |
| MAJOR-4 — Deep nesting/API normalization | A 1,200-level suite is normalized to `EvalSuiteLoadError`, and the API returns 422 `EVAL_SUITE_INVALID`; both retained probes pass. Depth and decoder handling are at `src/opsmind/evals/loader.py:56-73` and `src/opsmind/evals/models.py:39-102`. |
| MAJOR-5 — Fabricated run links | Completion without a run-reference verifier now fails closed and leaves the job `STARTED`; the retained persistence probe passes. The guard is at `src/opsmind/evals/persistence.py:99-111`. |
| MAJOR-6 — Terminal persistence lifecycle | When completed-job finalization fails, the runner performs a safe `FAILED` transition; the retained injected-outage probe observes durable `FAILED` and passes. The fallback is at `src/opsmind/evals/runner.py:64-94`. |

### Re-test validation evidence

```text
../opsmind-p1-007/.venv/bin/python -m pytest -q \
  tests/test_p1_008_independent_adversarial.py
→ 17 passed, 1 warning

../opsmind-p1-007/.venv/bin/python -m pytest
→ 554 passed, 1 deselected, 1 warning

../opsmind-p1-007/.venv/bin/ruff check .
→ PASS

../opsmind-p1-007/.venv/bin/mypy src
→ Success: no issues found in 51 source files

git diff --check
→ PASS

cd web && npm test
→ 4 files passed; 22 tests passed

cd web && npm run lint
→ PASS

cd web && npm run build
→ PASS

DEEPSEEK_API_KEY
→ absent; LIVE_EVAL_NOT_RUN
```

The only test warning is the pre-existing Starlette `TestClient`/`httpx`
deprecation warning. No product `src` or frontend files were changed by the
Tester, and no push or merge was performed.

### Final gate decision

Re-entry to Reviewer is approved from the independent Tester perspective:

```text
BLOCKER = 0
MAJOR = 0
MINOR = 0
NIT = 0
Reviewer Entry Gate = MET
```

PM Architecture Gate remains **PENDING** per
`docs/adr/ADR-004-eval-runtime.md`. Merge/push remain **PROHIBITED** for this
Tester task.
