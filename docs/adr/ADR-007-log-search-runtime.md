# ADR-007 — Scoped Log Search Runtime

Status: Proposed for TASK-P1-012. PM Architecture Gate pending.

Issue: #28

The authorized implementation adds a bounded, read-only `log_search` tool
through the existing ToolRegistry, review, current-run Evidence, and grounding
pipeline. It uses versioned synthetic local logs, a backend-neutral repository,
deterministic sanitization, and provider-free scoped retrieval.

Full logs must never enter model context or persistence. Only sanitized selected
events cross the tool boundary, with at most five events and a response below
12 KB. A trace ID or system plus query/error code is required. Queries are literal
text, with no regex or query language execution.

Implementation and complete decision rationale are pending. No graph, trust,
conversation semantics, external backend, Artifact Store, summarizer, inferred
root-cause field, or remediation capability is authorized by this ADR.

This ADR is not Accepted. Merge is prohibited pending user-controlled PM review.
