# TASK-P1-010 Final Independent Tester Report

## Verdict

`PASS`

- BLOCKER: 0
- MAJOR: 0
- MINOR: 0
- NIT: 0

The final Independent Tester gate is met.

## Exact reviewed identity

- Product SHA: `046eade22ce1fe5b7cf777aaa20e26e3077f4b29`
- Current PR tree / branch HEAD:
  `366f777a72fa523ffc72a0270b0d98ac18734187`
- Branch: `task/TASK-P1-010-dev`
- Base: `4d01d7c9995d86c91506e3d1f475050c113f75a3`
- PR: `#25`

The committed diff from Product SHA to the current PR tree contains only:

```text
M tasks/active/TASK-P1-010-conversation-persistence.md
A tasks/review/TASK-P1-010-final-reviewer-report.md
A tasks/review/TASK-P1-010-pm-architecture-handoff.md
M tasks/review/TASK-P1-010-reviewer-second-remediation-report.md
```

`git diff --exit-code 046eade..366f777 -- . ':(exclude)tasks/**'`
returned exit `0`. Therefore, current PR tree `366f777` contains no product,
test, `src`, `web`, `evals`, architecture, dependency, or configuration change
after Product SHA `046eade`; only task/reviewer/delivery artifacts follow it.

The working tree during final testing contains only this Tester's additional
test/report artifacts. No product implementation or product documentation was
modified.

## PR state verification

An independent GitHub query returned:

```json
{
  "number": 25,
  "state": "OPEN",
  "isDraft": true,
  "headRefName": "task/TASK-P1-010-dev",
  "headRefOid": "366f777a72fa523ffc72a0270b0d98ac18734187",
  "baseRefName": "main",
  "mergeStateStatus": "CLEAN"
}
```

PR #25 is open, Draft, and unmerged. Its remote head exactly matches the
current PR tree under review.

## Final focused acceptance

The final focused command collected and passed `153` tests across:

- all `test_p1_010*.py` Tester and Reviewer adversarial suites;
- conversation repository and real execution-boundary integration;
- P1-006 evidence/grounding adversarial regression;
- grounded response/API contracts;
- Eval suite, Eval runner, and evaluator behavior.

```text
153 passed, 1 warning
```

### Conversation persistence and continuity — PASS

- Fresh schema, idempotent initialization, independent version rejection,
  thread creation/detail/listing, contiguous sequence, revision, and checkpoint
  reload pass.
- Same-thread requests create new request/run IDs while retaining the thread.
- The deterministic two-run continuation restores `WO20260001`, classifies
  `CONTINUE_CASE`, and performs a new `work_order_query` for current-run
  evidence.
- ASK_USER continuation restores the original problem, prior clarification,
  unresolved context, and supplied follow-up identifier.
- Long threads remain fully durable while prompt-visible recent turns,
  checkpoint collections, and entity maps remain bounded.

### P0 context retention — PASS

- New identifier fields outrank non-ID noise at a full entity budget.
- Historical identifiers survive current-turn non-ID noise.
- `TARGET_ID`/`target_id` case variants produce the same projection for
  forward and reverse insertion order.
- Two input keys longer than 256 characters that truncate to one bounded key
  select the same documented lexical collision winner in both orders.
- Recent unresolved blockers survive full list budgets in chronological,
  unique order.
- No C12, query-text, `work_order_id`, entity-type, or fixture-value branch was
  found in the generic retention implementation.

### Identity and isolation boundaries — PASS

- `user_id` length 512 is persisted losslessly; length 513 is rejected with a
  typed data-integrity error and no conversation thread residue.
- At the API/execution boundary, 513-character user/site identities produce a
  sanitized 503, finalize the created AgentRun as `FAILED`, do not invoke the
  provider, and leave all three conversation tables empty.
- `site_id` length 512 is preserved exactly across runs and in the typed
  checkpoint/entity projection.
- Explicit different users cannot load or append to another user's thread.
- Explicit conflicting sites fail closed, do not advance the checkpoint, and
  release active-run ownership.
- An omitted site restores the allowlisted bound site; a model-guessed site
  cannot override explicit identity scope.
- Cross-thread tests prove that query, turns, checkpoint, facts, entities, and
  assistant content from Thread A are absent from Thread B.

### Concurrency, transactions, and failed runs — PASS

- In-process same-thread execution is serialized while different threads can
  proceed concurrently.
- Cross-repository active-run ownership and revision predicates reject lost
  updates.
- Deliberate assistant-turn and checkpoint persistence failures roll back the
  complete conversation terminal transaction.
- Runtime failure retains only the valid USER turn, creates no fake ASSISTANT
  turn, and does not advance the checkpoint.
- Terminal conversation failure returns a safe 503 without traceback/path
  leakage or fake conversation success.

### Evidence, leakage, and grounding regression — PASS

- Restored conversation history/checkpoint guides understanding but does not
  populate current-run `EvidenceState`.
- Follow-up current-status answers reacquire tool evidence in the new run.
- Grounded response planning still accepts only typed run-local evidence
  references; invalid IDs, paths, schemas, duplicates, nulls, and unregistered
  sources fail closed.
- Evidence IDs/order, not-found behavior, Unicode format controls, typed adapter
  validation, and control-plane/evidence separation pass.
- Conversation SQLite inspection excludes prompt/provider payload sentinels,
  chain-of-thought sentinel, arbitrary source context, credentials, and
  traceback/path sentinels while retaining permitted user/assistant content and
  typed projections.

### Golden C12 v0.2 and shared Eval path — PASS

- Golden Suite v0.1 remains immutable and v0.2 contains all eight cases.
- C12 v0.2 has no conversation-persistence known gap.
- Both C12 turns call the same `AgentExecutionService` used by Chat; no eval-only
  history concatenation exists.
- C12 reuses only its case-local thread, creates distinct request/run IDs,
  classifies turn 2 as `CONTINUE_CASE`, calls `work_order_query` with
  `WO20260001`, and grounds the result in turn-2 evidence.

## Full validation evidence

```text
.venv/bin/python -m pytest -q
629 passed, 1 deselected, 1 warning

.venv/bin/ruff check .
PASS

.venv/bin/mypy src
PASS — 56 source files

UV_CACHE_DIR=/tmp/... uv lock --check
PASS — 55 packages resolved

git diff --check
PASS

cd web && npm test -- --run
PASS — 41 tests

cd web && npm run lint
PASS

cd web && npm run build
PASS
```

The warning is the existing Starlette/httpx deprecation warning. The one
deselected test is credential-gated. No `DEEPSEEK_API_KEY` was present, so live
provider status is `LIVE_EVAL_NOT_RUN`.

Remote Python and Web CI for the current PR tree were also reported PASS by the
PM handoff. The verdict above relies on this Tester's independent local runs,
not on the remote result alone.

## Tester-only additions

- `tests/test_p1_010_final_tester_adversarial.py`
- `tasks/review/TASK-P1-010-final-independent-tester-report.md`

All earlier Tester FAIL and remediation reports remain unchanged. No product
code, `web` code, product docs, ADR, schema, Golden Suite, or dependency file
was modified.
