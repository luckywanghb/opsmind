# ADR-001 — Minimal LangGraph Agent Kernel

## Context

OpsMind has a canonical typed `OpsAgentState` and a provider-neutral
`ModelGateway`, but no executable Agent graph. Phase 1 needs a small runtime
that proves state propagation and structured model calls without introducing
tools or persistence.

## Decision

Use LangGraph with `OpsAgentState` as its state schema and inject one
`ModelGateway` into the graph factory. The graph is deliberately linear:

```text
START → understand_request → decide_action → END
```

Both nodes are asynchronous and call `invoke_structured` with the `CHEAP`
profile. Request understanding uses `REQUEST_UNDERSTANDING`; action decision
uses `ACTION_DECISION`. Each node returns a validated update for only its own
state section.

## State boundary

`OpsAgentState` remains the only canonical business state. The current
LangGraph version accepts the Pydantic model directly, so no duplicate
business-state schema or technical adapter is needed. Node-specific output
models are transient model-call contracts and are mapped into the canonical
`understanding` and `decision` sections after validation.

## Why LangGraph

LangGraph supplies explicit, inspectable node orchestration and async graph
execution while leaving model access, state contracts, and business reasoning
at the existing OpsMind boundaries.

## Why Mock-first

Deterministic `MockModelProvider` responses make graph order, profile/task
contracts, state propagation, context filtering, and failure behavior testable
without provider credentials or network access.

## Deferred capabilities

The following remain out of scope for ADR-001 and are superseded for the
TASK-P1-006 runtime by ADR-002: additional Agent domains, checkpoint/store/
thread persistence, interrupts and human approval, write actions, retrieval,
and Golden Case runtime branches.  ADR-002 adds only the bounded synthetic
read-only tool loop and its API/UI projection.

## Consequences

The original kernel remains the historical baseline for the architecture
decision.  The active topology is documented in ADR-002; future persistence,
write-capability, or approval changes require a new architecture review and
ADR.
