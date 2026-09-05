# ADR-003 — Agent Run Persistence and Observability Boundary

## Status

Proposed for TASK-P1-007; PM architecture gate required before merge.

## Context

The Phase-1 read-only Agent kernel returns a safe terminal result, canonical
compact evidence, and an actual safe trace, but those records disappear after
the HTTP request. Phase 2 evaluation and operational audit need a stable run
domain object that can be queried later without widening the model, tool, or
evidence trust boundaries established by ADR-002.

An HTTP request, an Agent run, and a conversation thread have different
lifecycles. Treating one of their IDs as another would make retry analysis,
future eval-case execution, and eventual conversation restoration ambiguous.

## Decision

Introduce a backend-neutral `RunRepository` contract, a
`RunPersistenceService` lifecycle/projection layer, and a local
`SQLiteRunRepository` implementation:

```text
FastAPI chat runtime
  → RunPersistenceService
    → RunRepository
      → SQLiteRunRepository
```

The service creates one `STARTED` record after public request validation and
before the Agent runtime starts. It finalizes the run as `SUCCEEDED` after the
existing public-safe projection is typed, or as `FAILED` with a normalized
error code after a catchable runtime failure. Completion time is UTC; duration
uses a monotonic clock.

Successful finalization replaces the terminal run columns and inserts every
safe trace step and canonical evidence item in one SQLite transaction. Failed
finalization similarly writes the normalized failure and any available safe
execution events atomically. Repository operations use a fresh connection;
there is no mutable module-global connection.

### Run, request, and thread identity

- `request_id` correlates one HTTP request and response.
- `run_id` is the stable primary identity of one Agent execution and is always
  new for a validated chat request, including a retry.
- `thread_id` correlates conversation continuity. Reusing it does not restore
  conversation state in this task.

One chat request therefore has one request ID and one run ID. A retry has new
request and run IDs while it may retain the same thread ID.

### Persistence placement

Persistence is an API/runtime-harness concern. No LangGraph persistence node,
conversation checkpointer, SQL call, or repository dependency is added to the
Agent graph, Agent nodes, model gateway, or tool harness. This keeps Agent
reasoning and graph topology unchanged and lets an eval runtime reuse the run
contract later.

### Evidence and trace boundary

The store accepts only typed post-projection objects:

- request understanding and latest action decision;
- ADR-002 safe trace events;
- canonical compact `EvidenceItem` values with stable IDs;
- grounded final reply and safe handoff;
- explicitly allowlisted source context (`channel`, `user_id`, `site_id`);
- terminal status, normalized error code, timing, and real runtime metadata.

Prompts, chain-of-thought, provider request/response payloads, raw model text,
raw tool results, arbitrary source context, traceback text, exception messages,
credentials, and filesystem paths never cross this boundary. JSON snapshots
are produced and revalidated by their Pydantic contracts; unknown JSON is not
treated as authoritative run data.

### Failure policy

Persistence is fail-closed. If the initial `STARTED` insert fails, Agent
execution does not begin. If terminal persistence fails, the API does not
return a successful chat result. Both cases produce the typed safe
`503 RUN_PERSISTENCE_UNAVAILABLE` response without database exception or path
details. A successfully created run ID is included in later error responses;
pre-run validation/creation failures do not claim that a run exists.

### Storage and schema

The default store is Python stdlib `sqlite3` at `.opsmind/opsmind.db`,
overridable by `OPSMIND_RUN_STORE_PATH`. SQLite matches the current
single-instance local demo and adds no database dependency. The version-1
schema has four tables: `schema_metadata`, `agent_runs`, `run_steps`, and
`evidence_records`. Initialization is idempotent and lock/transaction guarded;
an absent, invalid, or unsupported version on an existing run schema fails
explicitly.

SQLite is an implementation, not the domain boundary. PostgreSQL can replace
it behind `RunRepository` without changing the Agent graph.

## Alternatives rejected

- Writing `ChatResponse` blobs directly: it has no explicit lifecycle,
  transaction, schema-version, or child ordering contract.
- SQL inside graph nodes or tool execution: persistence would contaminate the
  model-driven business topology and make backend replacement expensive.
- LangGraph checkpointing: checkpoints restore graph/thread execution and are
  not an audit-oriented run record; conversation restoration is out of scope.
- SQLAlchemy/Alembic: unnecessary platform complexity for the first local
  versioned schema.
- PostgreSQL: distributed deployment and database operations are not required
  for the current local demo.
- Best-effort logging on persistence failure: it would report success for a
  run that the system promised but cannot later retrieve.

## Consequences

Every validated chat execution now has a stable queryable record suitable for
future eval references, audit, bad-case inspection, and version comparison.
Safe run summaries/details are available through read-only APIs. Local storage
now has a lifecycle and incompatible schema versions require explicit action.

This decision does not provide distributed database operation, retention or
cleanup policy, conversation restoration, eval execution, raw telemetry, RAG,
write tools, or UI pages. Long-running `STARTED` records may remain after a
process crash; recovery policy belongs to a later operational task.
