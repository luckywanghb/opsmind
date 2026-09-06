# TASK-P1-010 PM Architecture Gate Handoff

## Identity and status

- Base: `4d01d7c9995d86c91506e3d1f475050c113f75a3`
- Product HEAD: `046eade22ce1fe5b7cf777aaa20e26e3077f4b29`
- Delivery / Reviewed HEAD: `362468d81de9895632e351acea20a782c9476901`
- Issue: `#24`
- PR: `#25` (`DRAFT`, unmerged)
- CI on exact Reviewed HEAD: Python PASS; Web PASS

## Architecture

- ConversationRepository: typed backend-neutral persistence contract.
- SQLite Conversation Store: independent schema version 1 for threads, turns,
  checkpoints, ownership/revision, and deterministic sequence ordering.
- ADR-005: complete; application-harness persistence outside LangGraph.
- Context Restore Strategy: fresh Agent state plus typed checkpoint and at most
  six recent bounded turns; no previous loop/tool/decision/evidence state.
- Context Compression Strategy: bounded typed fields, recent P0 unresolved
  questions, deterministic ID priority, exact safe site identity continuity.
- Conversation / Run boundary: stable thread, new request ID and run ID per
  turn; Chat and Eval use the same execution service.
- Evidence boundary: history guides understanding only; factual replies still
  require current-run P1-006 Evidence.
- Concurrency policy: keyed in-process lock plus SQLite `BEGIN IMMEDIATE`,
  active ownership, and optimistic revisions.
- Failure policy: fail closed with typed sanitized errors; failed runs create
  no fake assistant/checkpoint advance; terminal conversation update is atomic.

## Product behavior

- Same-thread continuation: PASS; entity restored, CONTINUE_CASE understood,
  current facts reacquired through `work_order_query`.
- ASK_USER continuation: PASS without requiring full history resubmission.
- Cross-thread/user/site isolation: PASS, including identity conflicts and
  oversized identity boundaries.
- C12 result: PASS in Golden Suite 0.2; v0.1 retained unchanged; no case/query
  hardcoding.

## Validation

- Backend: `627 passed`, `1 deselected` (credential-gated), one dependency
  deprecation warning.
- Frontend: `41 passed`; lint PASS; production build PASS.
- Browser: PASS on real FastAPI + Vite deterministic two-turn flow.
- Eval: deterministic C12 real execution path PASS.
- Live DeepSeek: `LIVE_EVAL_NOT_RUN` (`DEEPSEEK_API_KEY` absent).
- Ruff: PASS.
- Mypy: PASS (`56` source files).
- Lock / diff: PASS.

## Independent gates

- Tester: `PASS`; BLOCKER 0 / MAJOR 0 / MINOR 0 / NIT 0.
- Sol Medium Reviewer: `APPROVE`; BLOCKER 0 / MAJOR 0 / MINOR 0 / NIT 0.

## Known limitations

- Local process locks are not distributed; repository conflicts protect peers.
- Process-crash active-claim recovery policy is deferred.
- Run and Conversation terminal writes are separate domain transactions.
- Transcript retention/cleanup automation is deferred.
- Live-provider quality was not measured without credentials.

## Explicitly not implemented

- RAG / `knowledge_search` / `log_search`
- Long-term user memory or user-preference memory
- LLM summarizer
- Chat history UI
- LangGraph checkpoint/resume
- Write tools
- Human approval workflow

## PM Architecture Gate

`PENDING`

## Merge

`PROHIBITED`
