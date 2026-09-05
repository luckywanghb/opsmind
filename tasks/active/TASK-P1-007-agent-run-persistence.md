# TASK-P1-007 — Agent Run Persistence & Observability Foundation

## Status

`IN_PROGRESS`

## Risk

`HIGH`

## Owner role

`Developer`

## Dependencies

- TASK-P1-006
- GitHub Issue #18

## Goal

Persist every validated `/api/v1/chat` Agent execution as a typed, queryable,
auditable run without changing P1-006 reasoning, graph topology, tool policy,
or evidence-grounding behavior.

## In scope

- independent request, run, and thread IDs;
- repository/service persistence boundary and stdlib SQLite backend;
- versioned idempotent schema and transactional lifecycle finalization;
- safe trace, canonical evidence, terminal output, timing, normalized error,
  and real runtime metadata;
- `GET /api/v1/runs` and `GET /api/v1/runs/{run_id}`;
- backend/frontend compatibility tests, ADR-003, and documentation.

## Out of scope

- eval runtime or UI;
- conversation persistence/checkpoint restoration;
- knowledge/RAG;
- Agent/model/tool configuration;
- write tools, approval flows, or new product UI.

## Architecture constraints

- SQL and SQLite must remain behind `RunRepository`.
- Persistence belongs to the API/runtime harness, not the LangGraph topology.
- Only P1-006 safe projections may be stored; no raw provider/tool payloads,
  prompts, hidden reasoning, traceback, secrets, or arbitrary source context.
- Persistence failures fail closed with typed safe API errors.

## Validation

Required before Developer handoff:

```bash
uv run --frozen pytest
uv run --frozen ruff check .
uv run --frozen mypy src
uv lock --check
cd web && npm test && npm run lint && npm run build
```

Independent Tester, Sol Medium Reviewer, CI, and PM Architecture Gate occur in
the later workflow stages. This branch must not be merged by the Developer.
