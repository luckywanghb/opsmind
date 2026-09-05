# OpsMind HTTP API

Status: Phase 2 run persistence foundation over the Phase 1 read-only loop

The API maps one request into the canonical `OpsAgentState`, runs the bounded
model-driven loop, and returns the terminal outcome plus an actual safe trace.

## Run locally

The default provider selector is the deterministic mock runtime:

```bash
OPSMIND_MODEL_PROVIDER=mock uv run --frozen uvicorn opsmind.api.app:create_app --factory
```

Agent runs are stored locally at `.opsmind/opsmind.db`. Override the location
without changing the Agent runtime:

```bash
OPSMIND_RUN_STORE_PATH=/var/tmp/opsmind.db \
  OPSMIND_MODEL_PROVIDER=mock \
  uv run --frozen uvicorn opsmind.api.app:create_app --factory
```

The directory is created on first use. An unsupported existing schema version
fails explicitly; startup never drops or silently rewrites a database.

Select the real DeepSeek provider explicitly:

```bash
export DEEPSEEK_API_KEY="..."
OPSMIND_MODEL_PROVIDER=deepseek uv run --frozen uvicorn opsmind.api.app:create_app --factory
```

If DeepSeek is selected without valid configuration, application construction
fails explicitly.  The runtime never silently falls back to mock.  Interactive
OpenAPI is available at `/docs`.

## Health

`GET /api/v1/health` checks only that the HTTP process can serve a request; it
does not call a provider.

```json
{"status": "ok", "service": "opsmind"}
```

Every response carries an `X-Request-ID` header.

## Chat

`POST /api/v1/chat` accepts one message and performs:

```text
ChatRequest → OpsAgentState → bounded Agent loop → ChatResponse
```

Example request:

```json
{
  "message": "WO20260001为什么一直没处理？",
  "thread_id": "plant-thread-7",
  "source_context": {
    "channel": "portal",
    "user_id": "U10023",
    "site_id": "星川基地"
  }
}
```

`message` must contain non-whitespace text and is limited to 8,000 characters.
`thread_id` is optional, need not be a UUID, and is limited to 128 characters;
the server generates a UUID when omitted.  `source_context` is a finite JSON
object.  Explicit `user_id` and `site_id` values are copied into synthetic
identity state; the runtime does not silently assume an authenticated user.
Undeclared request fields are rejected.

Successful responses include:

- independent `request_id`, `run_id`, and `thread_id` values;
- `status`: `completed`, `waiting_user`, `transferred`, `closed`, or the
  intermediate-compatible `decision_ready` value;
- validated `understanding` and latest model `decision`;
- `final_status`, a deterministic grounded `final_reply`, compact `evidence`
  with stable per-run IDs, and optional `handoff`;
- `trace`, containing only actual completed/failed/blocked model or harness
  steps with deterministic action/status summaries. The `decision.goal` and
  `decision.rationale` fields remain typed control-plane diagnostics; they are
  not evidence and are not used to render the final reply.

Example terminal response shape:

```json
{
  "request_id": "48ff5437-38f4-41b0-9c01-28e3a03ada40",
  "run_id": "b7506931-7522-4c3d-b828-56b42c639af5",
  "thread_id": "plant-thread-7",
  "status": "completed",
  "final_status": "RESOLVED",
  "understanding": {
    "primary_intent": "WORKFLOW_ISSUE",
    "request_type": "DIAGNOSE",
    "symptom": "工单正在审批",
    "entities": {"work_order_id": "WO20260001"},
    "risk_signal": "NONE",
    "uncertainty": null
  },
  "decision": {
    "action": "REPLY",
    "goal": "基于复核证据回复",
    "rationale": "证据已足够"
  },
  "final_reply": "来源 work_order_query：状态=APPROVING；来源 work_order_query：当前节点=设备主管审批；来源 work_order_query：当前处理人=U10108；来源 work_order_query：已等待=4 小时；来源 work_order_query：源异常标记=false；当前来源未提供原因、SLA 或阈值字段，无法据此得出未返回的业务结论。",
  "evidence": [
    {
      "evidence_id": "E1",
      "source": "work_order_query",
      "summary": "work_order_query: found",
      "key_fields": {
        "status": "APPROVING",
        "current_node": "设备主管审批",
        "current_handler": "U10108",
        "waiting_hours": 4,
        "abnormal": false
      },
      "metadata": {"result_status": "found", "reviewed": true},
      "artifact_ref": null,
      "timestamp": "2026-09-04T00:00:00Z"
    }
  ],
  "trace": [
    {"node": "understand_request", "task": "REQUEST_UNDERSTANDING", "profile": "CHEAP", "status": "completed", "summary": "WORKFLOW_ISSUE / DIAGNOSE"},
    {"node": "decide_action", "task": "ACTION_DECISION", "profile": "CHEAP", "status": "completed", "summary": "SEARCH"},
    {"node": "select_tool", "task": "TOOL_SELECTION", "profile": "CHEAP", "status": "completed", "summary": "work_order_query"},
    {"node": "execute_tool", "task": "TOOL_SELECTION", "profile": "HARNESS", "status": "completed", "summary": "work_order_query: found"},
    {"node": "review_tool_result", "task": "TOOL_RESULT_REVIEW", "profile": "CHEAP", "status": "completed", "summary": "TOOL_RESULT_REVIEW_COMPLETED"},
    {"node": "decide_action", "task": "ACTION_DECISION", "profile": "CHEAP", "status": "completed", "summary": "REPLY"},
    {"node": "generate_response", "task": "RESPONSE_GENERATION", "profile": "CHEAP", "status": "completed", "summary": "已生成最终回复"}
  ]
}
```

The API persists each execution, not conversation memory. A repeated
`thread_id` is a correlation value only; it does not restore or mutate a prior
run. Retrying creates a new request ID and run ID while retaining the supplied
thread ID.

## Run records

`GET /api/v1/runs?limit=50` returns newest-first summaries. `limit` defaults to
50 and must be between 1 and 100. A summary includes IDs, persistence
lifecycle, Agent terminal status, UTC timing, duration, and normalized error.

`GET /api/v1/runs/{run_id}` returns the complete safe run record:

- input and allowlisted source context (`channel`, `user_id`, `site_id`);
- typed understanding and latest decision for successful runs;
- ordered safe trace and canonical compact evidence;
- terminal status, grounded reply, safe handoff, and timing;
- normalized error code and runtime metadata actually known by the system.

The persistence lifecycle (`STARTED`, `SUCCEEDED`, `FAILED`) is independent
from the Agent terminal status. For example, `waiting_user` and `transferred`
are successful Agent executions. Unknown run IDs return `404 RUN_NOT_FOUND`.

The run store is not a raw logging sink. It never stores prompts,
chain-of-thought, provider payloads, raw model responses, raw tool-result
objects, tracebacks, exception/database text, credentials, or unallowlisted
source context.

## Tool and safety boundary

The current registry contains three synthetic typed read-only tools:

- `work_order_query` — status, approval node, handler, wait duration, anomaly;
- `permission_query` — roles, permissions, and missing permission facts;
- `incident_query` — incident ID, status, scope, and impact.

The model chooses from registered descriptions and schemas.  The harness
validates the call, applies `READ_ONLY`, enforces timeout/retry/round/tool-call
limits, executes the adapter, and keeps only compact reviewed evidence in
state.  Unknown records return typed `not_found`; unknown tools, malformed
arguments, and write-mode calls do not execute.

## Trace safety

Trace entries never expose chain-of-thought, prompts, raw provider requests,
raw tool-result blobs, source context, credentials, authorization headers, or
tracebacks.  A planned UI placeholder is never used for a completed step: the
UI renders the actual trace returned by this endpoint.

When a structured model node fails, internal logs may correlate the request ID
with an allowlisted node, expected schema name, logical profile, and sanitized
category.  These diagnostics are not included in the public error envelope.

## Errors

Errors use one envelope:

```json
{
  "error": {
    "code": "MODEL_INVOCATION_FAILED",
    "message": "Model invocation failed",
    "request_id": "b1f23478-408e-411f-873f-b3e38a6bccdb",
    "run_id": "b7506931-7522-4c3d-b828-56b42c639af5"
  }
}
```

`run_id` is present only after the initial run record was created. Request
validation or initial persistence failure does not claim a durable run ID.

| HTTP | Code | Meaning |
|---:|---|---|
| 400 | `INVALID_AGENT_INPUT` | Canonical kernel input was invalid. |
| 422 | `REQUEST_VALIDATION_FAILED` | Public request contract was invalid. |
| 502 | `MODEL_INVOCATION_FAILED` | Configured provider invocation failed. |
| 502 | `MODEL_STRUCTURED_OUTPUT_INVALID` | Model output failed its typed contract. |
| 503 | `RUN_PERSISTENCE_UNAVAILABLE` | Required run storage could not be completed safely. |
| 404 | `RUN_NOT_FOUND` | The requested run ID does not exist. |
| 500 | `INTERNAL_SERVER_ERROR` | Unexpected server failure. |

Error messages exclude prompts, model/provider payloads, source context,
credentials, adapter data, and internal exception text.

## Explicit limitations

This phase intentionally has no conversation checkpoints/thread resume, eval
runtime or UI, authentication, RAG, external enterprise integration, write
tools, approval interrupts, retention automation, or streaming. DeepSeek live
smoke is opt-in and is excluded from normal CI.
