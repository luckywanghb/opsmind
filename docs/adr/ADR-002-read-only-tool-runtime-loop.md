# ADR-002 — Generic Model-Driven Read-Only Tool Loop

## Status

Accepted for TASK-P1-006; PM architecture gate remains required before merge.

## Context

The Phase-1 kernel previously stopped after request understanding and one
action decision.  Issue #16 requires a demo-ready vertical slice that can
select and execute synthetic read-only tools, review their typed results, ask
the model whether more evidence is needed, and produce a grounded reply or
handoff.  D01–D03 are regression fixtures, not runtime cases.

## Decision

Keep `OpsAgentState` as the only canonical business state and evolve the
LangGraph topology to a bounded loop:

```text
understand_request → decide_action
  SEARCH → select_tool → execute_tool → review_tool_result → decide_action
  ASK_USER → generate_clarification → END
  REPLY → generate_response → END
  TRANSFER_HUMAN → generate_handoff → END
  END_CONVERSATION → close_conversation → END
```

The model selects a registered tool from runtime-provided descriptions and
JSON Schemas.  Python validates the selected name and typed arguments, checks
the hard `READ_ONLY` boundary, invokes the adapter with a bounded timeout, and
returns a normalized typed result.  The model reviews that result; the graph
does not map intent, wording, or demo identifiers to a tool.

The registry is copied per runtime and per graph run.  Tool results are
transient between execution and review.  Only compact review facts and an
`EvidenceItem` enter canonical state; adapter presentation messages and raw
payload blobs do not.

## Contracts and limits

The three task-scoped synthetic adapters are:

- `work_order_query` / `WorkOrderQueryRequest` / `WorkOrderQueryResponse`;
- `permission_query` / `PermissionQueryRequest` / `PermissionQueryResponse`;
- `incident_query` / `IncidentQueryRequest` / `IncidentQueryResponse`.

Unknown records return typed `not_found` results.  Unknown tools, malformed
arguments, malformed adapter results, timeouts, duplicate successful calls,
maximum rounds, maximum tool calls, and retry limits are handled by the
harness.  No persistence, retrieval, write capability, or LangGraph interrupt
is introduced.

## Trace and API impact

Trace entries are emitted only for actual completed, failed, or blocked model
and harness nodes.  They contain node, logical task/profile, status, and a
bounded safe summary; prompts, chain-of-thought, provider payloads,
credentials, and raw tool results are excluded.  The Chat response now exposes
terminal status, optional final reply, compact evidence, handoff data, and the
actual trace while retaining understanding and decision fields.

For Chinese input, prompts require Simplified Chinese for user-facing natural
language fields.  Enum values, schema keys, and tool names remain English.
The UI localizes presentation labels and renders actual tool/review/final nodes;
it does not synthesize successful execution.

## Consequences

The graph is reusable when additional typed read-only tools are registered and
does not require new semantic branches.  Existing two-node tests and docs are
migrated to the new contract.  A real DeepSeek D01 smoke remains opt-in and is
not part of normal CI; browser validation still requires the coordinated
configured runtime and ports reserved by the parent task.

## Alternatives rejected

- Case-specific `if/elif` routing by intent, wording, or fixture ID.
- Persisting full adapter output in `ToolState` or trace.
- Adding a write tool or approval interrupt before its own safety task.
- Keeping a legacy two-node graph solely to satisfy stale test fixtures.
