# TASK-P1-010 Independent Reviewer Report

## Decision

`REQUEST_CHANGES`

- BLOCKER: 0
- MAJOR: 2
- MINOR: 1
- NIT: 1

The Reviewer hard gate is not met because `MAJOR != 0`. This report does not
approve ADR-005, does not pass the PM Architecture Gate, and does not authorize
merge or conversion of Draft PR #25 to Ready.

## Reviewed identity

- Base: `4d01d7c9995d86c91506e3d1f475050c113f75a3`
- Reviewed HEAD: `a1ebf1fbefa7d9e67adfb6214501eb8944e42216`
- Draft PR: `#25` (`OPEN`, `DRAFT`)
- Remote PR base/head observed: exact Base/Reviewed HEAD above
- Exact-HEAD CI: `Python 3.11 validation` PASS; `Web client validation` PASS

I independently read the original attached task, repository task artifacts,
ADR-001 through ADR-005, the architecture/API/kernel and workflow documents,
all TASK-P1-010 Developer/Tester reports, the complete Base..HEAD diff, and the
conversation, execution, API, state, graph/context, Eval, Golden Suite, and
relevant regression tests. Reports were used only as leads.

## Findings

### MAJOR-1 — A new current-run P0 unresolved question is evicted when the checkpoint list is full

The task explicitly makes unresolved questions P0 context that must not
silently disappear under compression. `_bounded_items()` retains the first 20
unique values and stops (`src/opsmind/conversations/service.py:52-60`), and
`checkpoint_for()` applies it directly to the canonical unresolved-question
list (`src/opsmind/conversations/service.py:279-292`). In the real review path,
restored historical unresolved questions precede newly appended current-run
questions. Consequently, once 20 historical items fill the checkpoint, the
new blocker is discarded even though older P0 items survive.

Reviewer reproduction:

```text
20 older unresolved questions + 1 current blocker
checkpoint count: 20
current blocker retained: false
```

Evidence:
`tests/test_p1_010_reviewer_adversarial.py::test_checkpoint_retains_new_p0_unresolved_question_when_budget_is_full`.

Required remediation: define a deterministic priority/recency policy for the
bounded unresolved-question projection that guarantees current materially
blocking questions survive without unbounded growth. Cover a realistic
restored-history plus current-review append path.

### MAJOR-2 — Explicit safe `site_id` scope is not restored across runs

The task calls out `user_id`, `site_id`, and other important business IDs as
continuation anchors that must survive bounded context and reach tool
selection. The first run copies `site_id` into `IdentityState`, but neither
`ConversationThread` nor `ConversationCheckpoint` stores it
(`src/opsmind/conversations/models.py:44-58,88-117`). On a later same-thread
request, `build_fresh_state()` falls back to stored identity only for
`user_id`; absent current source context always makes `site_id=None`
(`src/opsmind/conversations/service.py:203-215`). `_important_entities()` also
projects only model-produced understanding entities, not the explicit safe
identity field (`src/opsmind/conversations/service.py:63-107`).

Reviewer reproduction:

```text
Run 1 source_context: user_id=U1, site_id=SITE-A
Run 2 same thread: user_id=U1, no repeated site_id
restored identity.user_id: U1
restored identity.site_id: null
restored important_entities: {}
```

This can make a continuation lose the site argument needed by a site-scoped
read-only query and ask the user to repeat context that the conversation
contract promises to retain.

Evidence:
`tests/test_p1_010_reviewer_adversarial.py::test_safe_site_identity_is_restored_when_followup_omits_source_context`.

Required remediation: retain and restore explicitly allowlisted safe site
scope at the typed conversation boundary, define conflict semantics if a later
explicit site differs, and keep arbitrary source context excluded.

### MINOR-1 — API documentation contradicts the implemented phase

`docs/API.md:294-299` says this phase has no conversation checkpoints/thread
resume and no Eval UI, while the same document and this task describe both
conversation checkpoint restoration and the already accepted Eval UI. This is
misleading durable API documentation and should be corrected to the actual
limitations (for example, no LangGraph checkpoint resume and no chat-history
UI).

### NIT-1 — Chat OpenAPI metadata omits documented 409 responses

The Chat route maps identity and concurrent update conflicts to documented 409
error codes, but its `responses` declaration lists 400/422/500/502/503 only
(`src/opsmind/api/app.py:470-480`). Add the 409 error model so generated API
documentation matches runtime behavior.

## Architecture and regression review

No additional blocking issue was found in these areas:

- Request, Run, and Conversation remain separate identities; same-thread runs
  get distinct request/run IDs and a stable thread ID.
- A fresh `OpsAgentState` is built from a typed checkpoint plus at most six
  bounded recent turns; old loop/tool/decision/response/evidence state is not
  restored and no LangGraph checkpointer or LLM summarizer was introduced.
- Historical turns, summaries, facts, and assistant text can affect request
  understanding, but do not populate current-run `EvidenceState` or
  `ResponsePlanContext`. P1-006 evidence-reference validation and grounded
  rendering remain current-run-only.
- SQLite uses an independent conversation schema version, fresh connections,
  `BEGIN IMMEDIATE`, active-run ownership, optimistic revisions, contiguous
  turn sequence, and one terminal assistant/checkpoint/thread transaction.
- Oversized `user_id` now returns sanitized 503, finalizes the already-created
  Run as FAILED, and leaves zero conversation thread/turn/checkpoint rows.
- Entity ordering now includes generic ID priority, source priority,
  case-folded and exact-key tie-breakers, plus deterministic long-key prefix
  collision resolution. The prior case-variant and 256-character truncation
  collision attacks pass; no C12/query/value branch exists in product code.
- Failed Agent runs retain only the USER turn and do not create a fake
  ASSISTANT turn or advance a checkpoint. Terminal conversation mutation is
  atomic and sanitized on failure.
- Explicit different-user continuation fails closed; cross-thread tests show
  no context crossover.
- Chat and Eval both call the same conversation-aware
  `AgentExecutionService`; Eval does not concatenate history or inject an
  eval-only state. Golden v0.1 is unchanged, while v0.2 changes only suite
  metadata and C12's resolved persistence gap/notes. P1-006/007/008 regression
  coverage remains active.
- No write capability, RAG, retrieval, vector database, long-term/cross-thread
  memory, chat-history UI, distributed store, or other prohibited scope was
  introduced.

## Independent validation

Before adding reviewer-only attacks:

```text
.venv/bin/python -m pytest -q
617 passed, 1 deselected, 1 warning

.venv/bin/ruff check .
PASS

.venv/bin/mypy src
PASS — 56 source files

UV_CACHE_DIR=/tmp/opsmind-review-uv-cache uv lock --check
PASS — 55 packages resolved

git diff --check Base..Reviewed-HEAD
PASS

cd web && npm test -- --run
PASS — 41 tests

cd web && npm run lint
PASS

cd web && npm run build
PASS
```

Reviewer-only focused attacks:

```text
.venv/bin/python -m pytest -q tests/test_p1_010_reviewer_adversarial.py -vv
2 failed
```

The two failures are exactly MAJOR-1 and MAJOR-2. The reviewer-only test file
does not modify product implementation. Its Ruff and diff checks pass.

`DEEPSEEK_API_KEY` is absent, so live multi-turn validation remains
`LIVE_EVAL_NOT_RUN`; no mock result is represented as live-provider quality.
An additional browser rerun was not necessary for these backend context
projection failures: existing real ChatPage integration coverage, the full
frontend suite, and exact-HEAD Web CI pass, while either MAJOR independently
blocks approval.

## Gate state

- Independent Tester: PASS at prior product candidate, BLOCKER 0 / MAJOR 0
- Independent Reviewer: REQUEST_CHANGES, BLOCKER 0 / MAJOR 2 / MINOR 1 / NIT 1
- PM Architecture Gate: PENDING
- Merge: PROHIBITED
- Draft to Ready: NOT AUTHORIZED
