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
never maps intent, wording, or demo IDs to a tool.  On later turns its context
includes the latest compact review projection and capabilities from the
run-local registry; review recommendations remain advisory.

`select_tool` receives runtime-registered descriptions and typed JSON Schemas,
then returns a validated `ToolState` selection.  The registry checks the name
and concrete request schema.  `execute_tool` enforces `READ_ONLY`, a bounded
timeout, duplicate-call protection, and normalized typed output.

`review_tool_result` calls `TOOL_RESULT_REVIEW` and projects a compact summary,
confirmed facts, unresolved questions, and an evidence item.  The next action
is selected by a fresh `decide_action` model call; review recommendations are
advisory and are not Python business routing.  Review receives the selected
tool's bounded output schema/semantics and available capability metadata.

Terminal nodes use `CLARIFICATION`, `RESPONSE_GENERATION`, and
`HANDOFF_GENERATION` to request a transient `GroundedResponsePlanOutput`, not
free-form user text. The plan contains only a terminal mode, bounded
presentation/limitation enums, clarification target, and
`EvidenceReference` (`evidence_id` plus canonical field path) values. For
Chinese input, prompts require Simplified Chinese for user-facing natural
language while enum values, schema keys, and tool names remain English.

The harness resolves every plan reference against stable per-run compact
evidence IDs and the selected tool's typed response schema. Unknown IDs,
unknown/missing/null fields, duplicate refs, extra prose fields, and terminal
mode mismatches fail closed before any reply is rendered. The deterministic
renderer obtains labels, units, value kinds and semantic markers from typed
tool presentation metadata, and emits source-qualified Simplified-Chinese
facts plus fixed limitation wording. It never consumes DecisionState goals or
rationales, review prose, or model-generated answer text. Thus elapsed time,
source flags, status values, permission facts and incident facts stay exactly
at their declared source meaning; absent cause/SLA/threshold/entitlement or
remediation evidence is stated as a limitation rather than inferred.

## Runtime limits and safety

The harness enforces maximum rounds, maximum tool calls, retry limits, and the
minimum of the state and per-tool timeout.  A repeated successful call is
blocked as a duplicate.  Write-mode registrations are rejected at execution
even if a model selects them.  Unknown records produce typed `not_found`
results; unknown tools or invalid arguments are rejected before adapter
execution.

## Trace and API boundary

Actual model and harness nodes emit safe trace events containing node, logical
task/profile, status, and a deterministic action/status summary. Decision
``goal``/``rationale`` and review prose remain control-plane state only; they
are not authoritative business facts in a public trace or UI. Prompts,
chain-of-thought, provider payloads, credentials, and raw tool results are not
exposed. Final text is produced only after a typed response plan selects
run-local evidence IDs/paths, deterministic validation resolves every field,
and the Simplified-Chinese renderer formats values from registered tool field
contracts. Any invalid reference or missing required field fails closed before
the API can expose a partial reply. The Chat API returns terminal status,
optional grounded final reply, compact evidence with stable per-run IDs,
handoff data, and this action/status-only trace.

Structured model-node failures additionally carry an internal,
request-correlated diagnostic containing only the node, expected response
schema name, logical profile, and a sanitized category.  The API logs those
allowlisted fields without exception chains and retains the same generic
public error envelope.

## Error behavior

The current query is required and invalid structured output still fails at the
typed gateway boundary.  Model/provider errors propagate to the API's
sanitized error envelope.  Structured adapter responses are checked for
finite JSON before review; a malformed result becomes the bounded
`MALFORMED_TOOL_RESULT` path.  Tool validation/policy failures are converted
to a safe handoff path; adapter failures are reviewed and bounded by
retry/loop limits.

## Current limitations

This task remains an in-memory single-Agent runtime.  It intentionally adds
no persistence/checkpoints, thread resume, RAG, external enterprise
integration, write actions, approval interrupts, authentication, or streaming.
The three synthetic adapters are fixtures for the generic registry and can be
replaced or extended by registration without semantic graph branches.
