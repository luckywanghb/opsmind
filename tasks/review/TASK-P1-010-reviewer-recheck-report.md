# TASK-P1-010 Independent Reviewer Recheck Report

## Decision

`REQUEST_CHANGES`

- BLOCKER: 0
- MAJOR: 1
- MINOR: 0
- NIT: 0

The Reviewer hard gate is still not met because `MAJOR != 0`. This recheck
does not pass the PM Architecture Gate, authorize merge, or authorize changing
Draft PR #25 to Ready.

## Reviewed identity

- Original review HEAD: `a1ebf1fbefa7d9e67adfb6214501eb8944e42216`
- Reviewer-remediation product SHA:
  `e8cafa4550224cfe366219fc5ef2d0dfd71a771e`
- Reviewed HEAD: `f6b39db737fe9bb4bb4c45895eb5253bbe6f9199`
- Base: `4d01d7c9995d86c91506e3d1f475050c113f75a3`
- Draft PR: `#25` (`OPEN`, `DRAFT`)
- Remote PR base/head: exact Base/Reviewed HEAD above
- Exact-HEAD CI: `Python 3.11 validation` PASS; `Web client validation` PASS

I preserved the original `TASK-P1-010-reviewer-report.md` unchanged. I read
the remediation report only as a lead, then independently reviewed the actual
`a1ebf1f..e8cafa4` product diff, current code, tests, documentation, and the
unchanged surrounding conversation/run/evidence/eval paths.

## Remediation result for prior findings

### Prior MAJOR-1 — FIXED

Unresolved P0 projection now scans newest-to-oldest, keeps the 20 most recent
unique bounded items, and reverses the selected set for chronological display
(`src/opsmind/conversations/service.py:64-74`). Independent checks covered:

- a current blocker following a full 20-item history;
- 21 older values plus a repeated older value and a current blocker;
- exact 20-item bound;
- newest duplicate wins;
- retained output remains chronologically ordered.

The current blocker survives, the oldest unique values are evicted, and the
output is deterministic and bounded.

### Prior MAJOR-2 — FIXED for valid checkpoint-sized site identities, but a new boundary MAJOR remains

For an ordinary explicit site value, the remediation now:

- stores typed `ConversationCheckpoint.site_id`;
- restores it into `IdentityState.site_id` and allowlisted
  `identity.source_context` when omitted;
- restores the explicit value into `important_entities`;
- lets explicit identity override a conflicting model-inferred `site_id`;
- does not restore arbitrary prior source-context fields;
- rejects a different later explicit site before model invocation;
- releases the lease and does not advance the prior checkpoint on conflict.

Those independent attacks pass.

### Prior MINOR-1 — FIXED

`docs/API.md` now accurately distinguishes application-level typed
conversation continuity from out-of-scope LangGraph execution resume and Chat
history UI, and correctly acknowledges the existing Eval UI.

### Prior NIT-1 — FIXED

The Chat OpenAPI operation declares a typed 409 `ErrorResponse`, and the
generated-schema regression assertion passes.

## New finding

### MAJOR-1 — Accepted 513-character `site_id` is lossy and conflicts with itself on the next run

The public `ChatRequest.source_context` accepts a finite JSON string without a
512-character `site_id` limit. The first fresh state therefore accepts the
full value. During successful finalization, both the checkpoint and important
entity silently truncate it to 512 characters
(`src/opsmind/conversations/service.py:100-105,318-329`), matching the new
checkpoint field's 512-character maximum
(`src/opsmind/conversations/models.py:96-98`). On the next same-thread request,
the conflict check compares the stored 512-character prefix against the
caller's identical original 513-character value
(`src/opsmind/conversations/service.py:215-227`) and returns
`409 CONVERSATION_IDENTITY_CONFLICT`.

Independent API reproduction:

```text
Run 1 explicit site_id: "S" * 513
Run 1 HTTP: 200
stored checkpoint site_id length: 512

Run 2 same thread, exact same explicit site_id: "S" * 513
Run 2 HTTP: 409 CONVERSATION_IDENTITY_CONFLICT
Run 2 AgentRun: FAILED
```

An identity value that the API accepted and reported successful must not become
unequal to itself solely through a lossy persistence projection. This breaks
same-thread continuity and makes the new identity-conflict policy reject a
non-conflict.

Evidence:
`tests/test_p1_010_reviewer_recheck_adversarial.py::test_accepted_site_identity_remains_equal_on_identical_continuation`.

Required remediation: align public/runtime/checkpoint site identity limits and
never silently truncate an identity used for equality. A value outside the
durable contract should fail through a typed safe boundary, or the durable
contract must preserve the accepted value exactly. Add the repeated-identical
boundary case alongside the different-site conflict case.

## Regression review

No other regression was found:

- The oversized `user_id` path remains sanitized 503 + Run FAILED + zero
  conversation residue.
- Generic entity priority remains order-independent, including case variants
  and over-256-character key-prefix collisions; no C12/query/value hardcode
  exists in product code.
- Fresh Run semantics, bounded recent context, cross-thread and different-user
  isolation, SQLite ownership/revision/sequence behavior, atomic terminal
  conversation updates, failed-run semantics, and sensitive-data projection
  remain intact.
- Historical conversation still does not enter current-run Evidence or the
  grounded response plan. P1-006 evidence validation/rendering is unchanged.
- Chat and Eval still use the same `AgentExecutionService`; Eval does not
  inject history. Golden v0.1 remains unchanged and v0.2 retains the intended
  C12-only continuity delta.
- No prohibited RAG, write action, LLM summarizer, LangGraph resume, long-term
  memory, Chat history UI, or distributed persistence scope was introduced.

## Independent validation

Reviewed-HEAD suite, excluding the newly added reviewer-only failing attack:

```text
.venv/bin/python -m pytest -q \
  --ignore=tests/test_p1_010_reviewer_recheck_adversarial.py
621 passed, 1 deselected, 1 warning

.venv/bin/ruff check .
PASS

.venv/bin/mypy src
PASS — 56 source files

UV_CACHE_DIR=/tmp/opsmind-review-recheck-uv-cache uv lock --check
PASS — 55 packages resolved

git diff --check a1ebf1f..f6b39db
PASS

cd web && npm test -- --run
PASS — 41 tests

cd web && npm run lint
PASS

cd web && npm run build
PASS
```

Independent reviewer-only recheck attacks:

```text
.venv/bin/python -m pytest -q \
  tests/test_p1_010_reviewer_recheck_adversarial.py -vv
3 passed, 1 failed
```

The passing tests independently cover unresolved ordering/deduplication/bound,
safe site restoration/allowlisting/explicit priority, and explicit conflict
checkpoint atomicity. The one failure is exactly the new MAJOR above. The
reviewer-only file does not modify product implementation.

`DEEPSEEK_API_KEY` remains absent, so live validation remains
`LIVE_EVAL_NOT_RUN`; no mock result is represented as live-provider quality.

## Gate state

- Independent Reviewer recheck: REQUEST_CHANGES
- BLOCKER: 0
- MAJOR: 1
- MINOR: 0
- NIT: 0
- Reviewed HEAD: `f6b39db737fe9bb4bb4c45895eb5253bbe6f9199`
- PM Architecture Gate: PENDING
- Merge: PROHIBITED
- Draft to Ready: NOT AUTHORIZED
