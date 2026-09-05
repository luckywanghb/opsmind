# TASK-P1-007 Developer Report

## Identity

- Task: TASK-P1-007 / GitHub Issue #18
- Role: Developer
- Branch: `task/TASK-P1-007-dev`
- Implementation commit: `b1dcac2f8184bc80c2f0d19ca4f3d5d789c66324`
- Base: `520c7b6e4bd2767003986644a36c89017463a617`
- Stage: TEST → Independent Tester / Reviewer
- Architecture impact: `ARCHITECTURE_CHANGE`
- PM Architecture Gate: `PENDING`
- Merge: `PROHIBITED`

## Outcome and architecture summary

- Added `AgentRun` as a typed domain record with an independent UUID
  `run_id`, persistence lifecycle (`STARTED`, `SUCCEEDED`, `FAILED`), Agent
  terminal status, safe input/context projection, UTC/monotonic timing,
  normalized error, runtime metadata, ordered safe trace, and canonical
  compact evidence.
- Added the explicit boundary `RunPersistenceService → RunRepository →
  SQLiteRunRepository`. The API/composition root injects the repository;
  Agent nodes, tools, model gateway, and business state do not import SQLite
  or execute SQL.
- The chat runtime creates `STARTED` after Pydantic request validation and
  before Agent execution. Success and failure finalization are transactional.
  Initial or terminal persistence failure returns safe typed
  `503 RUN_PERSISTENCE_UNAVAILABLE` and never returns false chat success.
- Persistence consumes the typed public-safe projection. It does not receive
  prompts, raw provider/model payloads, raw tool results, exception text, or
  arbitrary source context. Only `channel`, `user_id`, and `site_id` are
  allowlisted from `source_context`.
- Added request-local partial safe-trace capture for failed runs. This is an
  observability harness adaptation only: `run_ops_agent_with_trace` accepts an
  optional event sink and `OpsAgentRuntime` attaches the already-safe events
  to the original exception. Exception types, prompts, nodes, graph edges,
  routing, canonical state, tool execution, and business semantics are
  unchanged.
- Added ADR-003 and updated architecture, API, development, README, task, and
  frontend compatibility documentation/contracts.

## Database schema

Schema version: `1`, stored in `schema_metadata`.

- `agent_runs`: primary `run_id`, unique `request_id`, `thread_id`, lifecycle
  and Agent terminal status, safe input/source-context JSON, typed
  understanding/decision/handoff JSON snapshots, final reply, UTC timestamps,
  monotonic duration, normalized error, and runtime metadata JSON.
- `run_steps`: `(run_id, sequence)` primary key, node/task/profile/status/safe
  summary, foreign key to `agent_runs`.
- `evidence_records`: `(run_id, sequence)` primary key, unique
  `(run_id, evidence_id)`, validated canonical `EvidenceItem` JSON, foreign key
  to `agent_runs`.
- Indexes: unique request ID plus explicit thread ID, started-at, and lifecycle
  indexes.

Initialization is idempotent and guarded by a local initialization lock plus
`BEGIN IMMEDIATE`. Unknown/invalid versions and incomplete version-1 schemas
fail explicitly. Each operation opens its own connection with foreign keys and
a bounded busy timeout; there is no module-global connection. Final run,
steps, and evidence are committed or rolled back together.

## API changes

- `POST /api/v1/chat` success adds required `run_id`; existing response fields
  remain.
- Post-start error envelopes add optional `error.run_id`; validation and
  initial-persistence errors omit it.
- `GET /api/v1/runs?limit=50` returns newest-first typed summaries; limit is
  constrained to 1–100.
- `GET /api/v1/runs/{run_id}` returns the complete safe typed run record.
- Unknown run: `404 RUN_NOT_FOUND`.
- Persistence unavailable/corrupt/incompatible: safe
  `503 RUN_PERSISTENCE_UNAVAILABLE`.
- Default DB: `.opsmind/opsmind.db`; override with
  `OPSMIND_RUN_STORE_PATH`. Optional real build identity may be supplied with
  `OPSMIND_BUILD_SHA`; no prompt/model/knowledge versions are fabricated.

## Files changed

- Persistence domain: `src/opsmind/runs/{models,repository,service,sqlite}.py`
  and package exports.
- HTTP/runtime composition: `src/opsmind/api/app.py`,
  `run_observability.py`, `runtime.py`, `schemas.py`, `settings.py`.
- Safe trace hook only: `src/opsmind/agent/graph.py`.
- Backend tests/isolation: `tests/conftest.py`, `tests/test_run_api.py`,
  `tests/test_run_repository.py`, plus affected API/diagnostic tests.
- Frontend contract compatibility: `web/src/types/api.ts`,
  `web/src/api/opsmind.ts`, and affected tests.
- Documentation/governance: `.gitignore`, `README.md`, `docs/API.md`,
  `docs/ARCHITECTURE.md`, `docs/DEVELOPMENT.md`, ADR-003, and active task
  artifact.

## Tests added

Twenty-one new backend tests cover:

- fresh/repeated/versioned schema initialization and incompatible versions;
- STARTED, SUCCEEDED, and FAILED round trips;
- unique run/request IDs, get/list ordering, and limit;
- all-or-nothing finalization under injected evidence-insert failure;
- typed rejection of malformed stored JSON;
- allowlisted source context and monotonic timing;
- twelve concurrent run writes with ID/step/evidence isolation;
- chat-to-detail round trip, `waiting_user`/`transferred` lifecycle semantics,
  retry identity semantics, 404/422, and OpenAPI/config contracts;
- initial and terminal persistence fail-closed behavior;
- runtime/structured failures with normalized codes and ordered partial safe
  trace;
- direct SQLite leakage probes for prompt, provider payload, raw tool result,
  traceback/source-context sentinels while retaining legitimate input, safe
  trace, evidence, and grounded reply.

Frontend tests now require `run_id` on successful responses and preserve an
optional post-start error `run_id` for correlation.

## Validation evidence

Executed from the task worktree. Because a sandboxed `uv sync` could not
access the user cache/network, the frozen no-sync commands used the existing
Python 3.11 environment from the same repository/base while loading this
worktree through the configured `src` pythonpath. The lock was independently
checked offline and no dependency files changed.

```text
uv run --frozen --no-sync --active pytest
→ 476 passed, 1 live deselected, 1 existing deprecation warning

uv run --frozen --no-sync --active ruff check .
→ PASS

uv run --frozen --no-sync --active mypy src
→ Success: no issues found in 42 source files

uv lock --check --offline
→ Resolved 55 packages; PASS

git diff --exit-code -- uv.lock web/package-lock.json
→ PASS (no dependency-lock changes)

git diff --check
→ PASS

cd web && npm test
→ 4 files passed; 22 tests passed

cd web && npm run lint
→ PASS

cd web && npm run build
→ PASS
```

No live DeepSeek call or new browser feature acceptance was run, as specified
for this persistence-only task.

## Known limitations

- SQLite is for the current single-instance local runtime; no distributed
  writer coordination or PostgreSQL implementation exists yet.
- A process crash can leave a truthful `STARTED` record; automated stale-run
  recovery and retention/cleanup policy are not part of this task.
- Run listing has only bounded newest-first `limit`, without pagination or
  complex filters.
- JSON snapshots are schema-versioned and typed, but migration tooling is not
  introduced in version 1.
- Independent Tester, Sol Medium Reviewer, CI, and PM Architecture Gate remain
  pending; Developer does not declare the task DONE.

## Scope intentionally not implemented

- Eval runtime, Golden Case runner, judge, metrics, or Eval UI.
- Conversation persistence, LangGraph checkpoints, restoration, memory, or
  summary.
- Knowledge search, RAG, vectors, embeddings, or ingestion.
- Prompt/model/tool configuration, publish, rollback, or RBAC.
- Write tools, human approval, real enterprise integrations, streaming, or new
  Run UI.
