# OpsMind HTTP API

Status: Phase 1 runtime surface

The API exposes the existing two-node Agent kernel over HTTP. It does not add
persistence, tools, retrieval, streaming, or final-response generation.

## Run locally

The default provider selector is the reusable deterministic mock runtime. It
is offline and intended for tests and local contract demonstrations:

```bash
OPSMIND_MODEL_PROVIDER=mock uv run --frozen uvicorn opsmind.api.app:create_app --factory
```

Select the real DeepSeek provider explicitly:

```bash
export DEEPSEEK_API_KEY="..."
OPSMIND_MODEL_PROVIDER=deepseek uv run --frozen uvicorn opsmind.api.app:create_app --factory
```

If DeepSeek is selected without valid configuration, application construction
fails explicitly. The runtime never falls back to mock.

The interactive OpenAPI document is available at `/docs` while the server is
running.

## Health

`GET /api/v1/health` checks only that the HTTP process can serve a request. It
does not call or probe a model provider.

```json
{
  "status": "ok",
  "service": "opsmind"
}
```

Every response also carries an `X-Request-ID` header.

## Chat

`POST /api/v1/chat` accepts one message and performs exactly this boundary
flow:

```text
ChatRequest → OpsAgentState → run_ops_agent → ChatResponse
```

Example request:

```json
{
  "message": "Why is work order WO-42 still waiting?",
  "thread_id": "plant-thread-7",
  "source_context": {
    "channel": "portal",
    "site": "synthetic-plant-a"
  }
}
```

`message` must contain non-whitespace text and is limited to 8,000 characters.
`thread_id` is optional, need not be a UUID, and is limited to 128 characters;
the server generates a UUID when it is omitted. `source_context` must be a
finite JSON object. Undeclared request fields are rejected.

The message maps to both `conversation.original_query` and
`conversation.current_query`. The thread ID maps to
`conversation.thread_id`, and source context maps to
`identity.source_context`. The API invokes the canonical `run_ops_agent`
entry point rather than calling individual nodes.

Example response shape:

```json
{
  "request_id": "48ff5437-38f4-41b0-9c01-28e3a03ada40",
  "thread_id": "plant-thread-7",
  "status": "decision_ready",
  "understanding": {
    "primary_intent": "WORKFLOW_ISSUE",
    "request_type": "DIAGNOSE",
    "symptom": "Work order is waiting for approval",
    "entities": {"work_order": "WO-42"},
    "risk_signal": "NONE",
    "uncertainty": null
  },
  "decision": {
    "action": "SEARCH",
    "goal": "Inspect the current approval state",
    "rationale": "The current node is needed before explaining the delay"
  },
  "trace": [
    {
      "node": "understand_request",
      "task": "REQUEST_UNDERSTANDING",
      "profile": "CHEAP",
      "status": "completed",
      "summary": "WORKFLOW_ISSUE / DIAGNOSE"
    },
    {
      "node": "decide_action",
      "task": "ACTION_DECISION",
      "profile": "CHEAP",
      "status": "completed",
      "summary": "SEARCH: Inspect the current approval state"
    }
  ]
}
```

`decision_ready` means the current kernel produced request understanding and a
next-action decision. It is not a final answer. Trace entries come from actual
completed model invocations and expose only safe summaries; prompts, raw model
context, chain-of-thought, provider payloads, and credentials are excluded.

`request_id` identifies one HTTP request and is distinct from `thread_id`,
which identifies the caller's conversation. The service has no persistence in
this phase, so repeated thread IDs do not restore or mutate prior state.

## Errors

Errors use one envelope:

```json
{
  "error": {
    "code": "MODEL_INVOCATION_FAILED",
    "message": "Model invocation failed",
    "request_id": "b1f23478-408e-411f-873f-b3e38a6bccdb"
  }
}
```

| HTTP | Code | Meaning |
|---:|---|---|
| 400 | `INVALID_AGENT_INPUT` | The canonical kernel rejected its mapped input. |
| 422 | `REQUEST_VALIDATION_FAILED` | The public request contract was invalid. |
| 502 | `MODEL_INVOCATION_FAILED` | A configured provider invocation failed. |
| 502 | `MODEL_STRUCTURED_OUTPUT_INVALID` | Model output failed its typed contract. |
| 500 | `INTERNAL_SERVER_ERROR` | An unexpected server failure occurred. |

Error messages deliberately exclude raw prompts, model payloads, provider
details, source context, credentials, and internal exception text.

## Runtime boundary

The application is constructed with `create_app(...)`. Tests and embedding
runtimes can inject an `OpsAgentRuntime`; normal construction reads
`OPSMIND_MODEL_PROVIDER`. Request-scoped provider decorators record completed
invocations without changing the gateway, provider, graph, node, state, or
prompt contracts.

This phase intentionally has:

- no persistence or checkpoints;
- no tools or tool execution;
- no RAG or database integration;
- no streaming;
- no final-response generation;
- no UI.
