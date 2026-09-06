# TASK-P1-010 — Conversation Persistence & Context Continuity

## Status

`INDEPENDENT TEST PASS — REVIEWER PENDING`

## Risk

`HIGH` — introduces conversation persistence and cross-run context restoration.

## Control plane

- Issue: `#24`
- Branch: `task/TASK-P1-010-dev`
- Base: `4d01d7c9995d86c91506e3d1f475050c113f75a3`
- PR: `#25` (`DRAFT`)
- PM Architecture Gate: `PENDING`
- Merge: `PROHIBITED`

## Goal

Make a conversation thread a first-class, durable domain object. Each chat
request remains a fresh Agent run, while later runs in the same thread receive
a safe, bounded projection of the conversation required to understand a
continuation.

## Architecture constraints

- Keep HTTP requests, Agent runs, and conversation threads separate.
- Restore a typed conversation projection into a fresh `OpsAgentState`; never
  restore a previous run state or LangGraph checkpoint.
- Use a structured checkpoint plus bounded recent turns; add no LLM summarizer.
- Keep repository and SQL access in the application/execution harness.
- Conversation history may guide reasoning but is never current-run evidence.
- Persist no prompt, hidden reasoning, provider payload, raw model output, raw
  tool result, arbitrary source context, traceback, credentials, or full state.
- Preserve P1-006 grounding, P1-007 run persistence, and P1-008 eval execution.

## In scope

- Typed conversation thread, turn, checkpoint, and context models.
- Repository abstraction, SQLite implementation, independent schema/version.
- Lifecycle service with deterministic turn ordering and atomic terminal update.
- Same-thread serialization or safe conflict rejection and identity isolation.
- Context restoration and node-specific bounded context assembly.
- Safe persistence errors and read-only thread list/detail APIs.
- Multi-run deterministic integration, persistence, isolation, budget, failure,
  leakage, run/evidence/eval regression, and browser acceptance tests.
- Versioned Golden Suite update that resolves the C12 persistence known gap.
- ADR-005 and role reports.

## Explicitly out of scope

- RAG, knowledge/log search, embeddings, vector databases, or ingestion.
- Long-term/cross-thread/user-preference memory or profile extraction.
- LLM summarization, LangGraph checkpoint/resume, or approval interrupts.
- Chat history UI, rename/delete/search/pin, page-refresh restoration UI.
- Write tools, human approvals, auth platform, SSO/RBAC, streaming, queues,
  workers, distributed storage, or unrelated P1-009 debt.

## Required gates

- Developer validation: backend tests, Ruff, Mypy, lock, diff check, frontend
  tests/lint/build, deterministic browser acceptance, and credential-dependent
  live smoke status.
- Independent Tester: `PASS`, `BLOCKER=0`, `MAJOR=0`.
- Reviewer: `APPROVE`, `BLOCKER=0`, `MAJOR=0`.
- CI pass on the exact reviewed HEAD.
- PM Architecture Gate remains pending; no merge before approval.

## Developer validation snapshot

- Backend after Tester remediation: `616 passed`, `1 deselected`
  (credential-gated live test).
- Ruff: PASS.
- Mypy: PASS (`56` source files).
- Lock: PASS.
- Diff check: PASS.
- Frontend: `41 passed`; lint PASS; production build PASS.
- Browser: PASS — two real ChatPage turns used one thread, distinct request/run
  IDs, restored `WO20260001`, classified `CONTINUE_CASE`, reacquired current-run
  `work_order_query` evidence, and returned handler `U10108`.
- Live DeepSeek: `LIVE_EVAL_NOT_RUN` (`DEEPSEEK_API_KEY` unavailable).

## Independent test cycle

- Initial Tester verdict: `FAIL`, `BLOCKER=0`, `MAJOR=2`.
- Remediated invalid conversation identity normalization so the surrounding
  execution service terminates its already-created Run as `FAILED` and returns
  a sanitized typed persistence error.
- Replaced insertion-order entity truncation with deterministic priority:
  generic structured IDs (`id` / `*_id`) first, current-turn values before
  historical values within a class, then lexical order.
- First remediation retest: `FAIL`, `BLOCKER=0`, `MAJOR=1`; the original two
  MAJORs were fixed, but case-variant identifier keys exposed an incomplete
  tie-breaker.
- Second remediation adds the exact original key as the final ranking
  tie-breaker and deterministically resolves bounded-prefix collisions.
- Second remediation independent verdict: `PASS`, `BLOCKER=0`, `MAJOR=0`,
  `MINOR=0`, `NIT=0`; all prior FAIL reports remain retained.
