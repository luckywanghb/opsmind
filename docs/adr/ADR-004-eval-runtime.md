# ADR-004 — Backend-Owned Eval Runtime and Golden Suite

## Status

Proposed for TASK-P1-008; PM Architecture Gate remains required before merge.

## Context

P1-007 established a typed, auditable `AgentRun` record for one real Agent
execution. The product now needs a repeatable way to measure that runtime
against the eight V0.1 Golden Cases. The existing web fixture is presentation
data, contains capabilities that are not registered by the backend, and must
not silently become evaluation truth.

## Decision

Introduce a backend-owned, typed, versioned JSON Golden Suite and keep the
evaluation subsystem outside the Agent graph:

```text
EvalSuiteLoader
  → EvalRunner
    → AgentExecutionService
      → OpsAgentRuntime / RunPersistenceService
        → AgentRun
    → EvaluatorRegistry
      → EvalPersistenceService / SQLiteEvalRepository
```

`AgentExecutionService` owns the shared start → runtime → safe projection →
run finalization boundary. The Chat API and Eval Runner call that service; the
Eval Runner never calls the HTTP API and never duplicates Chat orchestration.
Every eval turn receives a new request ID and a real run ID. A case gets a
unique thread ID, and only turns within that case reuse it. The runner does
not inject prior state for C12, so a failure honestly exposes the absent
conversation-persistence capability.

The suite is `opsmind-golden` version `0.1` and contains C01, C03, C05, C06,
C09, C10, C11, and C12. Case IDs and assertion data remain in the eval
subsystem; Agent runtime, graph nodes, prompts, and tools do not inspect them.

## Safe evaluation observation

The shared execution service creates a transient typed observation containing
only request/run/thread identity, typed understanding and final decision,
bounded action sequence, validated tool name/arguments, loop counters,
canonical evidence, handoff state, terminal status, reply presence, and loop
convergence. It excludes prompts, hidden reasoning, provider requests or
responses, raw tool output, tracebacks, credentials, and arbitrary model text.
Evaluators consume this observation and persistence stores only bounded
assertion results, not the observation itself.

## Deterministic evaluators

The first registry implements generic evaluators for lifecycle, intent,
request type, risk, final action, terminal status, tool usage and arguments,
tool count, evidence count/source/fields, reply presence, handoff,
multi-turn identity continuity, and convergence. Grounding remains the
P1-006 typed Evidence-Bound renderer contract. No answer-text blacklist,
case-specific string matcher, semantic grader, or LLM-as-Judge is introduced.

An assertion can be blocking or informational. A case is `PASS` only when
the run is successful and all blocking assertions pass; a normal run with a
blocking mismatch is `FAIL`; a runtime/evaluator error is `ERROR`. A completed
Eval Job means the infrastructure completed the suite, not that every case
passed. `known_gap` explains expected capability gaps but never changes case
status.

## Persistence and schema

Eval persistence has its own `EvalRepository` contract and SQLite
implementation. It uses `eval_schema_metadata` version 1 plus
`eval_jobs`, `eval_case_results`, `eval_case_runs`, and
`eval_assertion_results` in the existing `.opsmind/opsmind.db` file. The
existing P1-007 `schema_metadata` and Run schema v1 remain untouched. Job
finalization and all child rows are one transaction. Before persistence, run
relations are checked against the real Run Repository so fabricated run IDs
cannot be stored.

## API

The backend exposes synchronous endpoints:

```text
POST /api/v1/evals/run
GET  /api/v1/evals
GET  /api/v1/evals/{eval_job_id}
```

The request selects only a backend-known `suite_id`; it cannot provide a
prompt, provider URL, model ID, or arbitrary cases. API responses expose job,
case, assertion, timing, known-gap, and real run-ID links only.

## Consequences and scope

The system can now produce an auditable, repeatable deterministic baseline
while honestly reporting C01/C09/C12 capability gaps. The frontend fixture
remains unchanged for P1-009. Prompt tuning, model routing changes, new
tools, RAG, log search, conversation restoration, write tools, queues, and
LLM judging remain intentionally out of scope.
