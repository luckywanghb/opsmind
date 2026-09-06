# TASK-P1-010 Developer Remediation Report

## Decision

`REMEDIATION COMPLETE — READY FOR INDEPENDENT RETEST`

## Trigger

The first independent Tester pass reported `BLOCKER=0`, `MAJOR=2`:

1. A 513-character `source_context.user_id` escaped the conversation
   persistence error boundary, returned HTTP 500, and left the already-created
   AgentRun in `STARTED`.
2. Entity checkpoint truncation stopped at capacity before evaluating a later
   current-turn structured identifier.

The original Tester report and adversarial tests are retained unchanged as
independent evidence.

## Remediation

### Typed conversation-start failure and run closure

Conversation start now normalizes Pydantic/domain validation failures and
storage decoding failures to `ConversationDataIntegrityError`. SQLite rolls
back the incomplete conversation transaction. `AgentExecutionService` already
handles the typed conversation persistence family by making a best-effort
AgentRun `FAILED` transition and returning the sanitized 503 contract.

No validation exception text, user value, traceback, or provider payload is
returned.

### Deterministic P0 entity retention

Checkpoint projection now evaluates all bounded scalar candidates before
truncation. Ranking is generic and independent of input dictionary order:

1. structured identifier keys (`id` or `*_id`),
2. current-turn values before historical values within the same class,
3. lexical key order as a stable tie-breaker.

This preserves active business identifiers without a C12 branch, exact query
match, fixture value, or work-order-specific key.

## Added regression coverage

- Repository-level invalid identity rollback and typed-error assertion.
- Repository/service-level full-budget retention using a different generic
  `asset_id` identifier.
- The independent Tester's original oversized-identity and `work_order_id`
  attacks now both pass.

## Validation

- Backend: `612 passed`, `1 deselected`, one dependency deprecation warning.
- Independent adversarial file plus repository tests: `14 passed`.
- Ruff: PASS.
- Mypy: PASS (`56` source files).
- `uv lock --check`: PASS.
- `git diff --check`: PASS.
- Frontend Vitest: `41 passed`.
- Frontend lint: PASS.
- Frontend production build: PASS.
- Live DeepSeek: `LIVE_EVAL_NOT_RUN` because `DEEPSEEK_API_KEY` is unavailable.

Developer does not self-approve. Independent Tester retest, Reviewer, exact
reviewed-HEAD CI, and PM Architecture Gate remain required. Merge remains
prohibited.
