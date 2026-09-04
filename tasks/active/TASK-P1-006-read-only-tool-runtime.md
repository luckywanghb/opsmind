# TASK-P1-006 — Read-only Tool Runtime & End-to-End Demo Loop

## Status

TEST — Architect remediation is implemented and validated on a new commit;
independent Tester and Reviewer stages plus the PM architecture gate remain
required.

## Source

GitHub Issue [#16](https://github.com/luckywanghb/opsmind/issues/16), including
the latest PM clarification that D01–D03 are acceptance fixtures and that the
runtime must remain generic and model-driven.

## Objective

Complete the in-memory Phase-1 Agent loop:

```text
understand → decide → select typed read-only tool → execute → review evidence
→ re-decide → reply / clarification / handoff
```

## In scope

- typed registry and synthetic adapters for work orders, permissions, and
  incidents;
- model-backed selection, result review, clarification, final reply, and
  handoff nodes;
- explicit latest-review and run-local capability context for re-decision,
  review, and terminal generation;
- bounded rounds/tool calls/retries/timeouts and deterministic READ_ONLY policy;
- compact evidence and actual safe trace/API projection;
- Simplified Chinese prompt contract and minimal UI localization/rendering;
- deterministic D01–D03, unseen-ID, safety, failure, and convergence tests;
- ADR-002 and Developer Report.

## Non-goals

No persistence/checkpoints, RAG, knowledge or log tools, external enterprise
integrations, write tools, authentication, approval interrupts, or case-specific
runtime branches.

## Acceptance anchors

- D01 selects `work_order_query` for `WO20260001`, reviews the approval facts,
  and can produce a Chinese grounded reply without claiming abnormality when
  `abnormal=false`.
- D02 selects `permission_query`; it reports only returned role/permission
  facts and does not infer entitlement.
- D03 selects `incident_query` and ends in model-selected reply or handoff
  without fabricated remediation.
- Unknown tool/arguments/records, adapter failures, repeated calls, limits,
  concurrent runs, raw-result leakage, and privileged write attempts are safe.

## Handoff

Developer Report: `tasks/review/TASK-P1-006-developer-report.md`.
Independent Tester and Reviewer must run after this implementation; no merge
or self-approval is authorized by this task artifact.
