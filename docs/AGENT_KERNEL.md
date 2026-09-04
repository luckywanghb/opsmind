# OpsMind Agent Kernel

The Phase-1 kernel is a single dependency-injected LangGraph run with a
bounded, model-first read-only loop:

```text
START
  ↓
understand_request [MODEL]
  ↓
decide_action [MODEL]
  ├─ ASK_USER → generate_clarification [MODEL] → END
  ├─ SEARCH → select_tool [MODEL]
  │             ↓
  │          typed validation + READ_ONLY policy [CODE]
  │             ↓
  │          execute_tool [CODE]
  │             ↓
  │          review_tool_result [MODEL]
  │             └──────────────► decide_action
  ├─ REPLY → generate_response [MODEL] → END
  ├─ TRANSFER_HUMAN → generate_handoff [MODEL] → END
  └─ END_CONVERSATION → close_conversation [CODE] → END
```

`OpsAgentState` remains the only canonical business state.  The graph copies
the injected `ToolRegistry` for each run; adapter output is transient between
`execute_tool` and `review_tool_result`.  Only compact review facts and
evidence summaries are retained in state.

## Node responsibilities

`understand_request` calls `REQUEST_UNDERSTANDING` with the `CHEAP` profile and
updates only `state.understanding`.

`decide_action` calls `ACTION_DECISION` with the `CHEAP` profile.  It is the
only control router; Python routes only on the validated model action and
never maps intent, wording, or demo IDs to a tool.

`select_tool` receives runtime-registered descriptions and typed JSON Schemas,
then returns a validated `ToolState` selection.  The registry checks the name
and concrete request schema.  `execute_tool` enforces `READ_ONLY`, a bounded
timeout, duplicate-call protection, and normalized typed output.

`review_tool_result` calls `TOOL_RESULT_REVIEW` and projects a compact summary,
confirmed facts, unresolved questions, and an evidence item.  The next action
is selected by a fresh `decide_action` model call; review recommendations are
advisory and are not Python business routing.

The terminal text nodes use `CLARIFICATION`, `RESPONSE_GENERATION`, and
`HANDOFF_GENERATION`.  For Chinese input, prompts require Simplified Chinese
for user-facing natural language while enum values, schema keys, and tool
names remain English.

## Runtime limits and safety

The harness enforces maximum rounds, maximum tool calls, retry limits, and the
minimum of the state and per-tool timeout.  A repeated successful call is
blocked as a duplicate.  Write-mode registrations are rejected at execution
even if a model selects them.  Unknown records produce typed `not_found`
results; unknown tools or invalid arguments are rejected before adapter
execution.

## Trace and API boundary

Actual model and harness nodes emit safe trace events containing node, logical
task/profile, status, and a bounded summary.  Prompts, chain-of-thought,
provider payloads, credentials, and raw tool results are not exposed.  The
Chat API returns terminal status, optional final reply, compact evidence,
handoff data, and this actual trace.

## Error behavior

The current query is required and invalid structured output still fails at the
typed gateway boundary.  Model/provider errors propagate to the API's
sanitized error envelope.  Tool validation/policy failures are converted to a
safe handoff path; adapter failures are reviewed and bounded by retry/loop
limits.

## Current limitations

This task remains an in-memory single-Agent runtime.  It intentionally adds
no persistence/checkpoints, thread resume, RAG, external enterprise
integration, write actions, approval interrupts, authentication, or streaming.
The three synthetic adapters are fixtures for the generic registry and can be
replaced or extended by registration without semantic graph branches.
