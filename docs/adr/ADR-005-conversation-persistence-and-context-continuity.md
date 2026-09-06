# ADR-005 — Conversation Persistence and Context Continuity

## Status

Implemented for TASK-P1-010. PM Architecture Gate pending.

## Context

`thread_id` currently correlates independent Agent runs but does not restore
conversation state. A follow-up request therefore starts with a fresh
`OpsAgentState` that cannot reliably recover the original problem, important
business entities, unresolved questions, or the prior clarification.

An HTTP request, Agent run, and conversation thread have different identities
and lifecycles. Conversation continuity must not turn an old run's decision,
loop counters, tool state, response state, or evidence into the starting state
of a new run.

## Decision

Introduce a backend-neutral `ConversationRepository`, an application-level
`ConversationPersistenceService`, and a versioned
`SQLiteConversationRepository`. The execution/application harness will:

```text
resolve/create thread
  → persist user turn
  → load typed checkpoint + bounded recent turns
  → build a fresh OpsAgentState
  → execute and persist a new AgentRun
  → atomically persist assistant turn + updated safe checkpoint
```

The default store has independent schema metadata version 1 and three domain
tables: `conversation_threads`, `conversation_turns`, and
`conversation_checkpoints`. Terminal assistant-turn and checkpoint mutation is
one SQLite transaction.

## Conversation, run, and request boundary

- `request_id` correlates one HTTP request/response.
- `run_id` identifies one fresh Agent execution.
- `thread_id` identifies the durable conversation containing multiple runs.

Reusing a thread never reuses a request ID or run ID.

## Persistence placement

Conversation persistence belongs to the application/execution harness. Agent
nodes, LangGraph, prompts, the tool harness, and model providers do not execute
SQL or own repository lifecycle.

## Restore and context strategy

Each request builds a fresh Agent state from the current request plus a typed
safe conversation projection. The projection combines a structured checkpoint
with the six most recent prior turns; each prompt-visible recent turn is capped
at 2,000 characters. Checkpoint lists and scalar entity maps are capped at 20
items, while the current and original query preserve the public 8,000-character
input contract. Full turns remain durable. Node-specific context assembly
gives the restored conversation fields to request understanding, while action
decision receives restored task/fact state and tool result review remains
current-run-only. Response-plan context is unchanged.

No LLM summarizer is introduced: it would add cost, latency, hallucinated
memory risk, structured-output failures, and a new behavior dependency where
canonical typed state already supplies a safe projection boundary.

## Evidence boundary

Historical turns and checkpoint fields can guide understanding, planning, and
entity recovery. They do not populate current-run `EvidenceItem` records and
cannot ground a final factual answer. Time-sensitive facts must be reacquired
through the existing P1-006 evidence pipeline in the current run.

## Concurrency

The application service uses a keyed async lock to serialize normal same-thread
requests within one process. SQLite `BEGIN IMMEDIATE`, an `active_run_id`
ownership column, and optimistic `revision` predicates detect concurrent peer
writers and reject them with `CONVERSATION_CONFLICT`; there is no silent
last-write-wins. This is intentionally a single-instance/local design, not a
distributed lock platform. A crashed process can leave an active claim that
requires later operational recovery policy.

## Storage

Python stdlib SQLite and a repository abstraction remain appropriate for the
single-instance local demo. Conversation tables use an independent schema
namespace and version in the existing configurable database file. Run and Eval
schema contracts remain unchanged.

## Failure policy

Conversation persistence is fail-closed. A storage failure maps to a typed,
sanitized service error and a safe HTTP response without SQL, database paths,
tracebacks, or exception text. Failed Agent runs do not create fake assistant
turns or advance the checkpoint with incomplete state. A USER turn is written
before Agent execution and retained for a failed run. Run and conversation
terminal commits remain separate domain transactions; this task does not add a
cross-domain distributed transaction.

## Evaluation and API

The Chat API and Eval Runner continue to call the same
`AgentExecutionService`; the composed service now owns conversation lifecycle.
Eval does not concatenate history. Golden Suite `0.2` retains the eight cases
and removes C12's conversation-persistence known gap. Read-only thread list and
detail endpoints expose typed metadata, ordered turns, run/request relations,
and safe checkpoint fields only.

## Consequences

The product gains auditable, bounded, same-thread cross-run continuity while
retaining independent Agent runs and current-run evidence grounding. It does
not gain long-term user memory, cross-thread preference memory, a chat-history
UI, LangGraph approval resume, retrieval, or write capabilities.
