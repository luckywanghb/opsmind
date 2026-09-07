# OpsMind

## Web client

Run the deterministic API and Vite client in separate terminals:

```bash
OPSMIND_MODEL_PROVIDER=mock uv run --frozen uvicorn opsmind.api.app:create_app --factory
```

Validated chat runs are persisted to `.opsmind/opsmind.db`. Set
`OPSMIND_RUN_STORE_PATH` to use a different local database path.

```bash
cd web
npm ci
npm run dev
```

The Vite development server proxies `/api` to `http://127.0.0.1:8000` by
default. Set `OPSMIND_API_PROXY_TARGET` for a different local backend target,
or `VITE_API_BASE_URL` when the browser should call an explicit API origin.

OpsMind is a production-shaped, fully synthetic manufacturing IT operations
Agent. It is built for learning and portfolio demonstration while preserving
typed contracts, stateful execution, observability, bounded loops, and hard
safety boundaries.

## Current status

- Phase 0 repository harness: complete
- Phase 1 Agent Kernel and read-only tool loop: implementation complete;
  independent test/review and PM architecture gate pending
- TASK-001 repository foundation and typed state: complete
- Minimal Agent kernel and DeepSeek provider integration: complete
- HTTP runtime: `GET /api/v1/health` and `POST /api/v1/chat`
- Run persistence: validated runs are queryable via `GET /api/v1/runs` and
  `GET /api/v1/runs/{run_id}`; typed conversation checkpoints/restoration are
  supported through repeated thread IDs
- Backend evaluation: the versioned V0.3 Golden Suite is runnable through
  `POST /api/v1/evals/run` and queryable via `GET /api/v1/evals`
- Phase 2 Evaluation & Observability: complete — TASK-P1-008 backend Eval
  Runtime and TASK-P1-009 real Eval UI delivered and PM-approved
- Runtime capability: `READ_ONLY` (three synthetic live-data query tools plus
  versioned local lexical `knowledge_search`)
- GitHub Issues and Pull Requests: development control plane
- Delivery Reporter: required at meaningful task transitions

The current implementation provides the validated V0.1 `OpsAgentState`, a
provider-neutral Model Gateway, a bounded model-driven LangGraph loop, typed
synthetic work-order/permission/incident queries, a versioned local knowledge
corpus with deterministic lexical retrieval, a typed FastAPI surface, and
versioned persistence for validated Agent runs plus a backend-owned
deterministic Golden Suite and eval runtime. The knowledge capability is a
bounded SOP/FAQ lookup; a general semantic RAG platform, external enterprise
knowledge connector, knowledge admin UI, and `log_search` remain absent.
D01–D03 are fixtures; the graph has no case-specific routing.

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
`tasks/done/`; the current Developer Report is staged at
`tasks/review/TASK-P1-006-developer-report.md`.
