# ADR-005 — Conversation Persistence and Context Continuity

## Status

Proposed for TASK-P1-010. PM Architecture Gate pending.

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

The detailed typed model, transaction, concurrency, context budgets, failure
mapping, and Eval integration will be finalized after inspecting and testing
the actual P1-009 main implementation.

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
with bounded recent turns. Node-specific context assembly decides which of
those fields each model task receives; the entire stored transcript is never
injected into every prompt.

No LLM summarizer is introduced: it would add cost, latency, hallucinated
memory risk, structured-output failures, and a new behavior dependency where
canonical typed state already supplies a safe projection boundary.

## Evidence boundary

Historical turns and checkpoint fields can guide understanding, planning, and
entity recovery. They do not populate current-run `EvidenceItem` records and
cannot ground a final factual answer. Time-sensitive facts must be reacquired
through the existing P1-006 evidence pipeline in the current run.

## Concurrency

The implementation will serialize same-thread mutation or reject detected
revision conflicts safely. It will not accept silent last-write-wins updates.
The final mechanism and its local SQLite limitations will be recorded here
after implementation validation.

## Storage

Python stdlib SQLite and a repository abstraction remain appropriate for the
single-instance local demo. Conversation tables use an independent schema
namespace and version in the existing configurable database file. Run and Eval
schema contracts remain unchanged.

## Failure policy

Conversation persistence is fail-closed. A storage failure maps to a typed,
sanitized service error and a safe HTTP response without SQL, database paths,
tracebacks, or exception text. Failed Agent runs do not create fake assistant
turns or advance the checkpoint with incomplete state.

## Consequences

The product gains auditable, bounded, same-thread cross-run continuity while
retaining independent Agent runs and current-run evidence grounding. It does
not gain long-term user memory, cross-thread preference memory, a chat-history
UI, LangGraph approval resume, retrieval, or write capabilities.

