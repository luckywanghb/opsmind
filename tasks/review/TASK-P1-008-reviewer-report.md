# TASK-P1-008 — Independent Reviewer Report

## Decision

`REQUEST_CHANGES`

```text
BLOCKER: 0
MAJOR: 4
MINOR: 0
NIT: 0
```

Reviewer Gate: **NOT MET**. Approval requires `BLOCKER = 0` and `MAJOR = 0`.

Escalation Architect: **NOT REQUIRED**. The findings are local execution,
module-boundary, evaluator-contract, Golden-data, and test-coverage defects;
they do not require a graph/prompt/tool/Run-schema architecture change and are
not repeated unresolved MAJOR findings from an earlier Reviewer cycle.

## Identity and independent review scope

- Role: Independent Reviewer (Sol Medium)
- Review branch: `task/TASK-P1-008-review`
- Base: `e0e0675d6c638401d91643aa546bb106b3188dca`
- Reviewed HEAD: `dddd35d`
- Product remediation commit in reviewed history: `f30cf21`
- Review range: `e0e0675..dddd35d`
- Product source/tests/Golden Suite modified by Reviewer: no
- Reviewer-only artifact: this report

The review independently read the supplied Task Specification, `AGENTS.md`,
ADR-002, ADR-003, ADR-004, the task artifact, Developer Report, initial/final
Tester Report, Developer Remediation Report, the complete changed-file list,
and the relevant implementation, persistence, suite, and test code. Existing
reports were used only as leads and not as substitutes for code inspection.

## Findings

### MAJOR-1 — The new shared execution module has an import-order-dependent cycle

`src/opsmind/execution.py:26` imports `opsmind.evals.models`. Importing that
submodule first initializes `opsmind.evals`, whose package initializer imports
the runner at `src/opsmind/evals/__init__.py:34`; the runner imports the
partially initialized execution module at `src/opsmind/evals/runner.py:20`.

Independent probe from a fresh interpreter:

```text
PYTHONPATH=src python -c 'from opsmind.execution import AgentExecutionService'
→ ImportError: cannot import name 'AgentExecutionError' from partially
  initialized module 'opsmind.execution'
```

The application currently happens to import `opsmind.evals` before
`opsmind.execution`, and the tests use the same favorable ordering, so the full
suite does not expose this failure. A shared architectural service must be
directly importable and must not depend on caller import order.

Required action: break the package cycle (for example, move the observation
contracts to a dependency-neutral module or stop eagerly importing the runner
from the eval package initializer) and add fresh-process/direct-import
regression coverage.

### MAJOR-2 — Eval observation validation can turn a successful Chat execution into a failed AgentRun

The shared service always constructs the eval-only observation before
persisting success (`src/opsmind/execution.py:274-279`) and catches any
observation projection/validation error as an Agent execution failure
(`src/opsmind/execution.py:280-294`). `ToolCallObservation` applies the eval
JSON limits to validated tool arguments, including a 512-character JSON string
limit (`src/opsmind/evals/models.py:39-78`, `:143-155`), while the existing
tool request contracts accept non-empty strings without that limit. Therefore
an otherwise valid and completed read-only tool call can now make `/api/v1/chat`
return an internal failure and persist the real run as `FAILED` solely because
the newly added eval projection rejected it.

Independent probe used an otherwise successful terminal state and a validated
`work_order_query` argument containing 600 characters. The shared service
returned `AgentExecutionError`; the durable run was `FAILED` with
`INTERNAL_SERVER_ERROR`. The existing `ToolState` accepts the same argument,
while `ToolCallObservation` rejects it. This violates the explicit requirement
that extracting `AgentExecutionService` must not change Chat/Agent business
semantics.

Required action: make safe observation projection unable to invalidate a
successful product execution. Preserve a bounded, typed indication suitable
for evaluator FAIL/ERROR without reclassifying Chat or its AgentRun, and add a
Chat regression for a valid tool argument at/above the eval projection bound.
Do not solve this by changing the frozen tool contracts or graph semantics.

### MAJOR-3 — Invalid evaluator return values escape the case ERROR boundary

`EvaluatorRegistry.evaluate` catches failures while invoking an evaluator, but
performs final `EvalAssertionResult.model_validate(result)` after the `try`
block (`src/opsmind/evals/evaluators.py:731-739`). A registered evaluator that
returns an invalid result object therefore raises raw `ValidationError` instead
of producing an assertion `ERROR`. The exception escapes `_run_case`, and
`run_suite` treats it as a fatal runner failure, making the Job `FAILED` rather
than completing the affected Case as `ERROR`.

Independent probe:

```text
EvaluatorRegistry({"bad": lambda assertion, context: {"invalid": "result"}})
  .evaluate(...)
→ escaped ValidationError
```

This contradicts the required semantics that evaluator errors are Case
`ERROR`, separate from Job infrastructure lifecycle. The required evaluator
test matrix is also incomplete: `tests/test_eval_evaluators.py:105-148` gives
all default evaluators a PASS path, but `:164-204` provides FAIL paths for only
five and invalid/error paths for only three, despite the specification
requiring PASS, FAIL, and invalid-observation coverage for every evaluator.

Required action: include result validation in the evaluator fail-closed
boundary, prove the runner completes the job with a Case `ERROR`, and add the
full per-evaluator PASS/FAIL/invalid matrix (including registered evaluator
failure and invalid-return behavior).

### MAJOR-4 — Golden Suite 0.1 omits explicit PM-owned truth assertions

The official backend suite does not encode all of the task's fixed core
expectations:

- C06 omits the required `request_type = DIAGNOSE` assertion
  (`evals/golden-v0.1.json:49-58`). A run classified as another request type can
  currently PASS C06.
- C05 lists the PM-owned synthetic truth `current_handler = U10108` and
  `waiting_hours = 4`, but asserts only status, node, and abnormal flag
  (`evals/golden-v0.1.json:34-45`). A response grounded in the wrong handler or
  waiting duration can currently PASS the formal case.

This weakens the backend Golden artifact and makes the baseline less honest
than the supplied specification. These are structured typed-evidence checks,
so adding them requires no answer-text matching, prompt tuning, or new product
capability.

Required action: add the missing blocking assertions to the still-unreleased
suite contract, retain suite identity/version handling consistent with the PM's
versioning decision, and add tests that demonstrate each wrong value fails.

## Architecture and scope review

The following requested boundaries were independently confirmed:

- Eval nodes were not added to the LangGraph topology. The graph delta is
  instrumentation for validated tool-call metadata; routing and edges are
  unchanged.
- No case ID or exact Golden message is inspected by Agent runtime, graph,
  prompt, or tool code.
- No prompt, model route, tool registry capability, Evidence contract,
  grounded renderer, or `READ_ONLY` behavior changed.
- The Golden Suite is backend-owned JSON and the frontend fixture remains
  untouched and is not imported by the backend.
- Evaluators are deterministic and data-driven; there is no final-answer
  blacklist, regex answer grader, semantic grader, or LLM-as-Judge.
- Case `PASS`/`FAIL`/`ERROR` and Job `STARTED`/`COMPLETED`/`FAILED` are modeled
  separately; normal quality failures do not fail the Job.
- C01, C09, and C12 are present, blocking, and not skipped or promoted by
  `known_gap`.
- C12 reuses only its case-local `thread_id`; it creates distinct request/run
  IDs and does not inject the first message, state, entity, or summary into the
  second turn.
- Eval persistence uses a separate repository/service and eval schema metadata,
  atomically writes terminal child rows, verifies real run references before
  commit, and preserves P1-007 Run schema v1.
- Safe eval persistence contains bounded assertion projections and run links,
  not prompts, provider payloads, raw tool outputs, arbitrary source context,
  exception messages, or tracebacks.
- There is no Eval UI, RAG/knowledge search, log search, conversation memory,
  write tool, queue, streaming eval, or other prohibited scope expansion.

## Six Tester MAJOR remediations

Independent code review and retained adversarial probes confirm the six
pre-remediation Tester findings are closed at the reviewed HEAD:

1. JSON equality is type-strict recursively; `false` no longer equals `0`.
2. Non-canonical terminal status becomes a safe evaluator `ERROR`.
3. Loader validation enforces evaluator-specific expectation shapes and turn
   bounds.
4. Deeply nested JSON is iteratively bounded and normalized to suite-load/API
   errors.
5. Missing run-reference verification now fails closed.
6. Completion-persistence failure attempts a safe durable `FAILED` transition.

All 17 retained independent adversarial tests pass. These closures do not
resolve the new MAJOR findings above.

## Independent validation evidence

Executed in `/Users/hongbo/vscode/agent/opsmind-p1-008-review` without network
access:

```text
../opsmind-p1-007/.venv/bin/python -m pytest
→ 554 passed, 1 deselected, 1 pre-existing deprecation warning

../opsmind-p1-007/.venv/bin/ruff check .
→ PASS

../opsmind-p1-007/.venv/bin/mypy src
→ PASS; no issues in 51 source files

UV_CACHE_DIR=/private/tmp/opsmind-p1-008-review-uv uv lock --check
→ PASS; resolved 55 packages from the existing lock/cache

git diff --check e0e0675..HEAD
→ PASS

cd web && npm test
→ 4 files passed; 22 tests passed

cd web && npm run lint
→ PASS

cd web && npm run build
→ PASS
```

The frontend commands reused the existing sibling worktree's `node_modules`
through a temporary symlink; the symlink was removed immediately afterward and
the review worktree was clean before this report was added.

`DEEPSEEK_API_KEY` was absent. Result: `LIVE_EVAL_NOT_RUN`. No credential value
was read or recorded.

## Gate handoff

```text
Decision: REQUEST_CHANGES
BLOCKER: 0
MAJOR: 4
MINOR: 0
NIT: 0
Reviewer Gate: NOT MET
Escalation Architect: NO
PM Architecture Gate: remains PENDING and is not announced by Reviewer
Merge/push: PROHIBITED
```
