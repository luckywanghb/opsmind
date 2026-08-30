# OpsMind

OpsMind is a production-shaped, fully synthetic manufacturing IT operations
Agent. It is built for learning and portfolio demonstration while preserving
typed contracts, stateful execution, observability, bounded loops, and hard
safety boundaries.

## Current status

- Phase 0 repository harness: complete
- Phase 1 Agent Kernel: in progress
- TASK-001 repository foundation and typed state: complete
- Runtime capability: `READ_ONLY`

The current implementation provides the validated V0.1 `OpsAgentState`
contract. Model Gateway, LangGraph execution, enterprise tools, and Golden Case
fixtures are intentionally deferred to later tasks.

## Development

Requires Python 3.11 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --dev
uv run pytest
uv run ruff check .
uv run mypy src
```

Architecture and development rules live in:

- `AGENTS.md`
- `docs/PRODUCT.md`
- `docs/ARCHITECTURE.md`
- `docs/DEVELOPMENT.md`
- `docs/PHASE1_PLAN.md`

Completed task artifacts, including tester and reviewer results, are stored in
`tasks/done/`.
