# OpsMind

OpsMind is a production-shaped, fully synthetic manufacturing IT operations
Agent. It is built for learning and portfolio demonstration while preserving
typed contracts, stateful execution, observability, bounded loops, and hard
safety boundaries.

## Current status

- Phase 0 repository harness: complete
- Phase 1 Agent Kernel: in progress
- TASK-001 repository foundation and typed state: complete
- Minimal Agent kernel and DeepSeek provider integration: complete
- HTTP runtime: `GET /api/v1/health` and `POST /api/v1/chat`
- Runtime capability: `READ_ONLY`
- GitHub Issues and Pull Requests: development control plane
- Delivery Reporter: required at meaningful task transitions

The current implementation provides the validated V0.1 `OpsAgentState`, a
provider-neutral Model Gateway, the two-node LangGraph kernel, and a typed
FastAPI surface. Enterprise tools and persistence remain intentionally absent.

## Development

Requires Python 3.11 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --dev
uv run pytest
uv run ruff check .
uv run mypy src
```

Run the deterministic offline API locally:

```bash
OPSMIND_MODEL_PROVIDER=mock uv run --frozen uvicorn opsmind.api.app:create_app --factory
```

For a real-model runtime, configure `DEEPSEEK_API_KEY` and select DeepSeek
explicitly:

```bash
OPSMIND_MODEL_PROVIDER=deepseek uv run --frozen uvicorn opsmind.api.app:create_app --factory
```

See [`docs/API.md`](docs/API.md) for request, response, runtime, and error
contracts.

Architecture and development rules live in:

- `AGENTS.md`
- `docs/PRODUCT.md`
- `docs/ARCHITECTURE.md`
- `docs/DEVELOPMENT.md`
- `docs/PHASE1_PLAN.md`
- `docs/REPORTING.md`
- `docs/roles/DELIVERY_REPORTER.md`

Completed task artifacts, including tester and reviewer results, are stored in
`tasks/done/`.
