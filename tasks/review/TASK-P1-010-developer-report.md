# TASK-P1-010 Developer Report

## Decision

`IMPLEMENTATION COMPLETE — READY FOR INDEPENDENT TEST`

## Identity

- Base SHA: `4d01d7c9995d86c91506e3d1f475050c113f75a3`
- Product HEAD: `f0f471414d10ddbce5e1f2edb4caec860ef3cde6`
- Issue: `#24`
- Draft PR: `#25`
- Branch: `task/TASK-P1-010-dev`

## Files changed

- Added `src/opsmind/conversations/` domain models, repository protocol,
  lifecycle/context service, and versioned SQLite implementation.
- Integrated conversation lifecycle into the shared `AgentExecutionService`
  used by Chat and Eval.
- Extended typed state and request-understanding context with bounded restored
  conversation fields.
- Added thread list/detail APIs and safe error mappings.
- Added immutable Golden Suite `0.2`; retained `golden-v0.1.json` unchanged.
- Added persistence, transaction, budget, isolation, identity, failure,
  leakage, real multi-run, ASK_USER continuation, Eval C12, and API tests.
- Updated architecture, kernel, API, task, and ADR-005 documentation.

## Architecture summary

`ConversationThread`, `ConversationTurn`, and `ConversationCheckpoint` are
separate typed domain objects. `ConversationPersistenceService` sits in the
application harness above `ConversationRepository`; graph nodes and tools do
not know SQL. Each request creates a new request/run, then restores only safe
conversation-level state into a fresh `OpsAgentState`.

## Conversation domain and DB schema

- `conversation_threads`: lifecycle, original query, identity binding, latest
  run, turn count, revision, and active-run ownership.
- `conversation_turns`: UUID turn identity, contiguous per-thread sequence,
  role, safe content, request/run relation, timestamp.
- `conversation_checkpoints`: typed checkpoint JSON, revision, timestamp.
- `conversation_schema_metadata`: independent schema version `1`.
- Terminal assistant-turn and checkpoint updates are one SQLite transaction.

## Context restoration and budget policy

- Full turns remain durable; prompts receive at most six prior turns.
- Each restored recent turn is capped at 2,000 characters.
- Checkpoint lists and scalar important-entity maps are capped at 20 items.
- Current and original queries retain the public 8,000-character contract.
- Request Understanding receives original/current query, recent turns,
  checkpoint summary, task/facts, important entities, last assistant reply,
  resolution state, and current safe source context.
- Action Decision receives restored task/facts through fresh canonical state.
- Tool Review remains current-run-only; ResponsePlanContext is unchanged.
- Historical conversation never populates current-run Evidence.

## Concurrency and failure policy

- A keyed async lock serializes same-thread calls in one process.
- SQLite `BEGIN IMMEDIATE`, `active_run_id`, and optimistic revision predicates
  reject peer conflicts; there is no silent last-write-wins.
- Conversation persistence failures fail closed with sanitized typed errors.
- Failed Agent runs retain USER turns, create no fake ASSISTANT turn, and do
  not advance checkpoints.
- Identity-bound threads reject a different explicit `user_id`.

## API and Eval changes

- `POST /api/v1/chat` remains input-compatible and now restores server-owned
  context for an existing thread.
- Added `GET /api/v1/threads?limit=50` and
  `GET /api/v1/threads/{thread_id}`.
- Golden Suite default is `opsmind-golden` `0.2`; all eight cases remain and
  C12 no longer carries the conversation-persistence known gap.
- C12 turns go through the same conversation-aware execution service as Chat;
  no eval-only history concatenation exists.

## Tests and validation

- Backend: `608 passed`, `1 deselected`.
- Ruff: PASS.
- Mypy: PASS (`56` source files).
- `uv lock --check`: PASS.
- `git diff --check`: PASS.
- Frontend Vitest: `41 passed`.
- Frontend lint: PASS.
- Frontend production build: PASS.
- Browser: PASS using real FastAPI, real Vite, deterministic provider, and
  temporary SQLite. Turn 2 retained one thread, used distinct request/run IDs,
  classified `CONTINUE_CASE`, restored `WO20260001`, called
  `work_order_query` again, and grounded handler `U10108` in current-run
  Evidence.
- Live DeepSeek: `LIVE_EVAL_NOT_RUN` because `DEEPSEEK_API_KEY` is unavailable.

## Known limitations

- Local process locks are not distributed; repository ownership detects peer
  conflicts. A process crash can leave an active claim for future operational
  recovery policy.
- Run and Conversation terminal commits are separate domain transactions; no
  cross-domain distributed transaction was introduced.
- Full transcript retention/cleanup policy is deferred.

## Explicit scope exclusions

No RAG, knowledge/log search, vector DB, long-term/cross-thread memory, user
preferences, LLM summarizer, Chat history UI, LangGraph checkpoint/resume,
write tools, human approval, auth platform, streaming, queue, worker, or
distributed database was added.

Developer does not declare the task done. Independent Tester, Reviewer, CI,
and PM Architecture Gate remain required. Merge remains prohibited.
