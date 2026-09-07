# OpsMind HTTP API

Status: Phase 3 conversation continuity and bounded knowledge retrieval over the persistent read-only runtime

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

The default registry exposes `work_order_query`, `permission_query`,
`incident_query`, and the read-only `knowledge_search` capability. The latter
searches the versioned local SOP corpus and returns at most one best matching
chunk. A knowledge evidence item contains stable document/chunk provenance and
the selected excerpt; it never contains the manifest source path or unselected
document content.

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

The API persists each execution and its conversation relationship separately.
A repeated `thread_id` restores a typed checkpoint plus at most six recent
turns into a fresh Agent state. It never restores the prior run's loop, tool,
decision, response, or Evidence state. Retrying creates a new request ID and
run ID while retaining the supplied thread ID.

If a thread is bound to a `user_id`, a later request with a different explicit
`user_id` fails closed with `409 CONVERSATION_IDENTITY_CONFLICT`. A same-thread
checkpoint also retains an explicit safe `site_id`; a later different explicit
`site_id` fails with the same identity-conflict code, while omission restores
the stored site scope. Identity values are limited to 512 characters; an
out-of-contract value fails safely and is never truncated. Arbitrary prior
source-context fields are not restored.
A same-thread
concurrent mutation is serialized in-process and protected by repository
ownership/revision checks; a detected peer conflict returns
`409 CONVERSATION_CONFLICT`.

Conversation storage failure returns the sanitized
`503 CONVERSATION_PERSISTENCE_UNAVAILABLE` response. A failed Agent run keeps
its USER turn for audit, creates no fake ASSISTANT turn, and does not advance
the checkpoint.

## Conversation records

`GET /api/v1/threads?limit=50` returns newest-first thread metadata. `limit`
defaults to 50 and is bounded from 1 through 100.

`GET /api/v1/threads/{thread_id}` returns thread metadata, deterministically
ordered turns with request/run relations, and the current safe checkpoint.
Unknown IDs return `404 CONVERSATION_NOT_FOUND`.

The conversation schema uses independent `conversation_schema_metadata`
version 1 plus `conversation_threads`, `conversation_turns`, and
`conversation_checkpoints` in the configured SQLite file. It stores user
messages, safe terminal assistant replies, and typed bounded checkpoint fields.
It excludes prompts, hidden reasoning, provider payloads, raw model/tool
output, arbitrary source context, exception text, credentials, and full prior
Agent state.

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

## Evaluation

The backend owns the typed Golden Suite at `evals/golden-v0.3.json`. It
contains the eight inherited cases plus C13 and is loaded and integrity-checked
before a job is created. C01 and C13 exercise the real registered
`knowledge_search` runtime; C09 remains the `LOG_SEARCH_NOT_IMPLEMENTED` known
gap. The API accepts only a backend-known `suite_id`; callers cannot
submit arbitrary cases, prompts, provider settings, or evaluator code.

```text
POST /api/v1/evals/run
GET  /api/v1/evals?limit=20
GET  /api/v1/evals/{eval_job_id}
```

Start a suite run:

```json
{"suite_id": "opsmind-golden"}
```

Every turn goes through the same conversation-aware execution service as Chat, with a fresh
request ID and real persisted `AgentRun`. Turns in one case share a generated
thread ID; separate cases do not. C12 now validates real durable restoration,
continuation understanding, retained work-order identity, and a new current-run
tool query. Golden v0.1 remains immutable historical input.

The returned job has lifecycle `STARTED`, `COMPLETED`, or `FAILED`; each case
has quality status `PASS`, `FAIL`, or `ERROR`. A completed job means the suite
infrastructure completed, not that every case passed. Deterministic
assertions inspect safe typed observations (not answer-text matching or an
LLM judge). `known_gap` is explanatory metadata only.

Eval rows use independent `eval_schema_metadata` version 1 and eval tables in
the same SQLite file. The existing Run schema remains version 1 and is not
modified. Eval persistence stores assertion results and real run links, not
prompts, hidden reasoning, provider payloads, raw tool results, tracebacks,
credentials, or arbitrary source context.

## Tool and safety boundary

The current registry contains four typed read-only tools:

- `work_order_query` — status, approval node, handler, wait duration, anomaly;
- `permission_query` — roles, permissions, and missing permission facts;
- `incident_query` — incident ID, status, scope, and impact.
- `knowledge_search` — one best versioned SOP/FAQ chunk, stable provenance,
  optional exact `system_id` scope, and typed `not_found`.

The model chooses from registered descriptions and schemas.  The harness
validates the call, applies `READ_ONLY`, enforces timeout/retry/round/tool-call
limits, executes the adapter, and keeps only compact reviewed evidence in
state. Knowledge requests are bounded to a 512-character query and a
128-character system scope. Unknown records return typed `not_found`; unknown
tools, malformed arguments, and write-mode calls do not execute. The local
knowledge repository accepts only validated ACTIVE documents and keeps
manifest source paths inside its storage boundary.

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

This phase intentionally has no LangGraph execution checkpoint/resume,
chat-history UI, authentication, general semantic RAG platform, external
enterprise knowledge connector, knowledge administration API, write tools,
approval interrupts, retention automation, or streaming. It does include the
bounded local lexical `knowledge_search` runtime described above. Conversation
continuity uses the typed application-level checkpoint, and the existing Eval
UI remains available. DeepSeek live evaluation is opt-in and is excluded from
normal CI.
