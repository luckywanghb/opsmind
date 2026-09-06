# TASK-P1-010 — Conversation Persistence & Context Continuity

## Status

`IN PROGRESS — DEVELOPMENT`

## Risk

`HIGH` — introduces conversation persistence and cross-run context restoration.

## Control plane

- Issue: `#24`
- Branch: `task/TASK-P1-010-dev`
- Base: `4d01d7c9995d86c91506e3d1f475050c113f75a3`
- PR: `PENDING DRAFT CREATION`
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

