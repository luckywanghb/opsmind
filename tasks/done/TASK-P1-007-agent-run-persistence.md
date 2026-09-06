# TASK-P1-007 — Agent Run Persistence & Observability Foundation

## Status

`DONE`

## Risk

`HIGH`

## Owner role

`PM/Architect`

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

## Final gate

- Product HEAD reviewed: `9a9abc060fa9e8e5580465746b83487f1999b3bd`
- Independent Tester: `PASS` — BLOCKER 0 / MAJOR 0 / MINOR 0 / NIT 0
- Sol Medium Reviewer: `APPROVE` — BLOCKER 0 / MAJOR 0 / MINOR 0 / NIT 0
- GitHub Actions: Python and Web validation `PASS`
- PM Architecture Gate: `APPROVED FOR MERGE` on 2026-09-06
- ADR-003: `Accepted`

The governance-only gate closeout introduces no product or test changes after
the reviewed product HEAD. TASK-P1-008 is the recommended next task but is not
started here.
