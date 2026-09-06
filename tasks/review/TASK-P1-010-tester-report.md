# TASK-P1-010 Independent Tester Report

## Verdict

`FAIL`

- BLOCKER: 0
- MAJOR: 2
- MINOR: 0
- NIT: 0

Reviewer hard gate is not met because `MAJOR != 0`. Product remediation and an
independent retest are required before Reviewer/PM Architecture Gate.

## Reviewed identity

- Base: `4d01d7c9995d86c91506e3d1f475050c113f75a3`
- Product HEAD: `f0f471414d10ddbce5e1f2edb4caec860ef3cde6`
- Worktree HEAD during test: `01360654973b2e074132c26af2ea82768d5b3fa3`
- The only committed change after Product HEAD is the Developer Report; there
  is no later product or product-test change.
- Draft PR: `#25`

I independently read the user task, ADR-005, the P1-006/P1-007/P1-008 task
boundaries, conversation models/service/repository/SQLite implementation,
shared execution service, Chat/thread APIs, node-specific contexts, Eval
runner, Golden Suite 0.2, and the relevant tests. The Developer Report was not
used as acceptance evidence.

## Findings

### MAJOR-1 — Schema-valid identity input returns 500 and strands the run in STARTED

**Requirement violated:** safe persistence failure semantics; every accepted
Chat execution must have a terminal persisted run; safe 422/503 behavior; no
failed-run lifecycle corruption.

`ChatRequest.source_context` accepts a finite JSON object without applying the
conversation domain's 512-character `user_id` limit
(`src/opsmind/api/schemas.py:30-39`). `AgentExecutionService` first persists a
STARTED run and then forwards the raw string to conversation persistence
(`src/opsmind/execution.py:342-358`). A new thread constructs
`ConversationThread`, whose `user_id` is capped at 512 characters
(`src/opsmind/conversations/models.py:44-58` and
`src/opsmind/conversations/sqlite.py:183-195`). The resulting Pydantic
`ValidationError` is not one of the errors normalized by `begin_run`
(`src/opsmind/conversations/sqlite.py:277-288`) and is not caught by the
conversation-start cleanup block, which catches only
`ConversationPersistenceError` (`src/opsmind/execution.py:350-368`).

Independent reproduction:

```text
POST /api/v1/chat
source_context.user_id = "U" repeated 513 times

actual HTTP status: 500 INTERNAL_SERVER_ERROR
actual persisted run lifecycle: STARTED
```

The input passes the public request schema, no model call is required, and the
run remains falsely in progress indefinitely. Evidence is captured by
`tests/test_p1_010_independent_adversarial.py:18-43`.

**Required remediation outcome:** align validation/normalization across the
public, run, and conversation boundaries, return a typed safe error, and
guarantee that every exception after `RunPersistenceService.start()` makes a
best-effort terminal FAILED transition without exposing validation text.

### MAJOR-2 — Full entity budget silently drops a newly observed P0 business identifier

**Requirement violated:** context compression must preserve P0 critical
entities/business IDs; bounded context may discard lower-priority material but
must not silently discard the active business object.

`_important_entities` iterates the model's scalar entity mapping and stops as
soon as the map reaches 20 items (`src/opsmind/conversations/service.py:63-75`).
Therefore, when 20 auxiliary scalar entities precede a newly supplied
`work_order_id`, the identifier is never projected into the checkpoint. The
checkpoint directly persists this result
(`src/opsmind/conversations/service.py:248-266`).

Independent reproduction constructs an otherwise valid fresh state containing
20 auxiliary scalar entities followed by `work_order_id=WO20260001`.

```text
actual checkpoint important_entities count: 20
actual checkpoint work_order_id: missing (KeyError)
```

Evidence is captured by
`tests/test_p1_010_independent_adversarial.py:46-85`. This is not merely a size
assertion: it proves loss of the exact P0 object needed for later continuation.
After recent turns age out, neither the structured checkpoint nor the bounded
history is guaranteed to retain the identifier.

**Required remediation outcome:** define and test a deterministic, generic P0
retention policy that does not depend on arbitrary dictionary order and does
not hardcode C12, its wording, or `WO20260001`.

## Areas independently checked without a new finding

- Existing deterministic multi-run and ASK_USER tests exercise fresh runs,
  same-thread restoration, distinct request/run IDs, continuation
  classification, tool re-query, and current-run evidence.
- Historical checkpoint/turn data is restored into conversation/task/facts,
  not into `EvidenceState`; Tool Result Review and grounded response-plan
  contexts retain the P1-006 current-run evidence boundary.
- SQLite uses `BEGIN IMMEDIATE`, active-run ownership, revision predicates, and
  atomic assistant-turn/checkpoint/thread terminal updates. Existing deliberate
  assistant/checkpoint failure tests pass.
- Existing explicit different-user and cross-thread isolation tests pass.
- Eval C12 calls the same `AgentExecutionService` for both turns. No eval-only
  history concatenation or case/query branch was found in `src/`.
- Golden Suite 0.1 is retained and 0.2 removes only C12's conversation known
  gap while preserving the eight cases.
- Conversation persistence remains behind its repository/service boundary; no
  LangGraph checkpoint, full-state restore, LLM summarizer, write tool, or
  unrelated scope expansion was found.
- Existing SQLite sentinel tests found no prompt, provider payload, hidden
  reasoning, arbitrary source context, credential, or traceback leakage in
  conversation tables. User/assistant turns and safe typed checkpoint fields
  remain the intended durable content.

## Validation evidence

Before adding independent adversarial tests:

```text
.venv/bin/python -m pytest -q
608 passed, 1 deselected, 1 warning
```

After adding the two independent acceptance tests:

```text
.venv/bin/python -m pytest -q
2 failed, 608 passed, 1 deselected, 1 warning
```

The two failures are exactly MAJOR-1 and MAJOR-2 above.

Other gates:

```text
.venv/bin/ruff check .                         PASS
.venv/bin/mypy src                             PASS (56 source files)
UV_CACHE_DIR=/tmp/... uv lock --check          PASS
git diff --check                               PASS
cd web && npm test -- --run                    PASS (41 tests)
cd web && npm run lint                         PASS
cd web && npm run build                        PASS
```

The repository's deterministic real-execution Chat/Eval integration coverage
passed within the 608 baseline tests, including C12's shared service path.
`DEEPSEEK_API_KEY` was absent, so live-provider validation is
`LIVE_EVAL_NOT_RUN`. A separate browser rerun was not used to override the two
backend acceptance failures; the task remains FAIL regardless of browser UI
behavior.

## Tester changes

Added test-only evidence:

- `tests/test_p1_010_independent_adversarial.py`

No product implementation was modified.
