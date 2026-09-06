# TASK-P1-008 — Eval Runtime & Golden Suite

## Status

`READY_TO_MERGE` (`PM_GATE_APPROVED`)

## Risk

`HIGH` — introduced a persistence and execution boundary covered by ADR-004,
independent Tester/Reviewer gates, and the PM Architecture Gate approved on
2026-09-06.

## Owner role

`Developer`

## Dependencies

- TASK-P1-007 — Agent Run Persistence & Observability Foundation
- Existing V0.1 Agent Kernel, read-only tool runtime, and synthetic adapters

## Goal

Add a backend-owned, typed, deterministic evaluation runtime for the eight V0.1
Golden Cases. Each eval turn must execute the real Agent runtime, create a real
persisted `AgentRun`, and produce auditable case/assertion results without
making the eval subsystem part of the Agent graph.

## In scope

- Versioned `evals/golden-v0.1.json` containing C01, C03, C05, C06, C09, C10,
  C11, and C12.
- Strict suite/case/turn/assertion loading with evaluator-integrity checks.
- Generic deterministic evaluators over safe typed observations, including
  intent, request type, risk, action, tool usage/arguments, evidence,
  handoff, identity continuity, and loop convergence.
- A shared `AgentExecutionService` used by Chat and Eval for one real run
  lifecycle and safe terminal projection.
- Transactional eval job persistence behind `EvalRepository`, with a separate
  versioned eval schema in the existing SQLite file and real run-ID links.
- Synchronous `POST /api/v1/evals/run`, `GET /api/v1/evals`, and
  `GET /api/v1/evals/{eval_job_id}` endpoints.
- Implementation, adversarial/boundary tests, ADR-004, active task artifact,
  and Developer Report.

## Out of scope / non-goals

- No graph topology, prompt, model-routing, tool registry, Evidence contract,
  grounded renderer, or `READ_ONLY` policy changes.
- No case-specific routing, exact-answer matching, LLM judge, RAG/log search,
  conversation checkpoint restoration, write tool, approval flow, queue, or
  Eval UI.
- No changes to the P1-007 Run schema version or existing API semantics.

## Acceptance criteria

- The backend Golden Suite is typed, versioned, deterministic, bounded, and
  rejects malformed, duplicate, oversized, or unknown-evaluator content.
- A completed job distinguishes PASS, FAIL, and ERROR case quality from job
  infrastructure lifecycle and records every real Agent run relation.
- Blocking assertion failures produce case `FAIL`; runtime/evaluator failures
  produce case `ERROR`; `known_gap` never turns a failure into a pass.
- Multi-turn cases reuse only a case-local thread ID and create distinct
  request/run IDs per turn.
- Eval persistence finalization is atomic and rejects orphan run references;
  schema incompatibility fails explicitly without destructive migration.
- Public errors remain typed and safe; prompts, hidden reasoning, raw provider
  payloads, raw tool results, tracebacks, credentials, and arbitrary source
  context are not stored in eval records.
- Existing Chat behavior and read-only Agent semantics remain unchanged.

## Required validation

```bash
../opsmind-p1-007/.venv/bin/python -m pytest
../opsmind-p1-007/.venv/bin/ruff check .
../opsmind-p1-007/.venv/bin/mypy src
uv lock --check
git diff --check
cd web && npm test && npm run lint && npm run build
```

DeepSeek live evaluation is opt-in. When `DEEPSEEK_API_KEY` is absent, record
`LIVE_EVAL_NOT_RUN` without exposing the key. When present, run the backend
Golden Suite through the explicitly selected DeepSeek runtime and record the
result separately from deterministic/offline validation.

## Handoff state

Developer implementation has passed the final independent Tester and Reviewer
gates after the required local validation. GitHub PR #21 passed Python and Web
validation on delivery HEAD `dc9888a0a39708ec74328e7e0c068128a3158b48`.
The PM Architecture Gate approved ADR-004 and authorized squash merge on
2026-09-06. A governance-only closure commit is the final pre-merge change;
product, test, Eval behavior, and Golden expectations remain unchanged.
