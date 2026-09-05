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

## Architect remediation delta

The final architecture correction keeps the topology and canonical state
unchanged while repairing the model context boundaries:

- Action-decision context now carries a typed latest-review projection
  (`evidence_sufficient`, advisory `recommended_action`, review summary,
  result status/error, selected tool and selection goal), compact source
  evidence, and bounded capability metadata from the graph's run-local
  registry.
- Result review receives the selected tool's output-field schema and semantics,
  the current task/selection goal, prior compact evidence, and the same
  run-local capability metadata.  Terminal response, clarification, and
  handoff contexts receive bounded capability metadata and latest-review state
  as well.
- A shared bounded-answer policy distinguishes “sufficient for a useful,
  explicitly limited answer” from complete knowledge.  Unresolved questions
  are not an automatic clarification checklist; `ASK_USER` requires a specific
  materially blocking user-suppliable fact, and `SEARCH` requires a registered
  capability that can address the gap. Review recommendations remain advisory;
  a fresh model action decision owns routing.
- Shared terminal grounding rules preserve relevant returned identifiers,
  ownership/state, quantities/units and source flags, while prohibiting
  unsupported SLA/timeout, progression, universal-normality, unexecuted-call,
  unavailable-capability, or write/remediation claims.  No prose postprocessor
  or case-specific rule was added.

The registry dependency is explicitly injected by the graph into every node
that needs capability metadata.  Nodes do not construct a hidden default
registry, and capability/schema metadata is not persisted in canonical state.

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

The remediation keeps this boundary explicit: model-facing review schemas
preserve their JSON Schema structure (including nested types, enums, refs,
`anyOf` branches and nullability) while only human-readable annotations are
bounded.  Adapter responses are revalidated and recursively checked for
finite JSON before they can reach review or evidence projection; malformed
results become the existing bounded `MALFORMED_TOOL_RESULT` failure path.
Structured model-node failures attach an internal, request-correlated
allowlist containing only node, expected schema name, logical profile and a
sanitized category.  API responses remain the generic error envelope and do
not expose prompts, model text, payloads, validation input or exception
chains.  Trace summaries are capped at a fixed length at the event boundary.

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

## PM Architecture Amendment — Evidence-Bound User-Facing Output

The PM architecture decision in Issue #16
(`AUTHORIZE_GENERIC_RELIABILITY_ARCHITECTURE`) adds a hard output-grounding
boundary without changing the generic loop or model-owned routing.

Terminal model nodes now return a transient `GroundedResponsePlanOutput` only:

- a terminal mode (`REPLY`, `ASK_USER`, `TRANSFER_HUMAN`, or
  `END_CONVERSATION`);
- a bounded presentation intent/limitation enum; and
- zero or more `EvidenceReference` values containing a run-local evidence ID
  and canonical field path.

The plan has no answer, claim, summary, or other free-form factual field. The
review projector assigns stable per-run IDs (`E1`, `E2`, ...), and the model
sees typed field/presentation metadata from the registered tool contract. The
harness resolves every ID/path against the compact evidence and response
schema before rendering. Any unknown ID, unknown path, missing/null field,
duplicate reference, extra plan field, or terminal-mode mismatch fails closed
as a sanitized structured-node error; no partial text is rendered.

The deterministic Simplified-Chinese renderer emits source-qualified labels,
units, values, and boolean flags from the resolved typed fields only. Fixed
limitation templates cover absent causal, SLA/threshold, entitlement,
remediation, scope, and match evidence. An elapsed duration remains an
elapsed duration, `false` remains the source flag `false`, and neither becomes
a progression, normality, timeout, entitlement, or remediation conclusion.
Decision goals/rationales and review prose remain control-plane model text;
they are absent from the grounded plan context, ignored by the renderer, and
public traces use deterministic action/node summaries.

## Alternatives rejected

- Case-specific `if/elif` routing by intent, wording, or fixture ID.
- Persisting full adapter output in `ToolState` or trace.
- Adding a write tool or approval interrupt before its own safety task.
- Keeping a legacy two-node graph solely to satisfy stale test fixtures.
