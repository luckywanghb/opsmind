# TASK-P1-008 — Eval Runtime & Golden Suite

## Identity

- Task: `TASK-P1-008`
- Role: `Developer`
- Branch: `task/TASK-P1-008-dev`
- Base SHA: `e0e0675d6c638401d91643aa546bb106b3188dca`
- Implementation commit: `0b01dda`
- Stage: `TEST` → independent Tester / Reviewer
- Architecture impact: `ARCHITECTURE_CHANGE`
- PM Architecture Gate: `PENDING`
- Merge: `PROHIBITED`

## Outcome and architecture summary

- Added the backend-owned, typed, versioned suite `opsmind-golden` `0.1` in
  `evals/golden-v0.1.json` for C01, C03, C05, C06, C09, C10, C11, and C12.
- Added strict suite/case/turn/assertion loading with bounded JSON, duplicate
  ID checks, and evaluator-registry integrity checks.
- Added generic deterministic evaluators for lifecycle, intent, request type,
  risk, action, tool usage and arguments, evidence, handoff, reply presence,
  identity continuity, and loop convergence. No answer-text matcher or LLM
  judge is used.
- Added `AgentExecutionService` as the shared Chat/Eval execution boundary.
  Each eval turn creates a real persisted `AgentRun`, with a fresh request/run
  ID and a case-local thread ID reused only within that case.
- Added independent eval persistence through
  `EvalPersistenceService → EvalRepository → SQLiteEvalRepository`, with eval
  schema version 1 and atomic job finalization linked to real run IDs.
- Added synchronous `POST /api/v1/evals/run`, `GET /api/v1/evals`, and
  `GET /api/v1/evals/{eval_job_id}` endpoints with typed safe projections.
- Added ADR-004 and updated the task-linked API, architecture, development,
  and README documentation.

## Safety and scope guard

- Eval observations and persisted rows contain only bounded typed metadata,
  safe understanding/decision projections, validated tool metadata, loop
  counters, canonical evidence, handoff state, and real run links.
- Prompts, hidden reasoning, provider payloads, raw tool results, tracebacks,
  credentials, and arbitrary source context are not persisted.
- C01, C09, and C12 remain honest capability-gap cases. `known_gap` is
  explanatory only and never converts a failed case into a pass.
- No graph topology, prompt, model routing, tool registry, Evidence contract,
  grounded renderer, read-only policy, RAG/log search, conversation
  persistence, write tool, or Eval UI changes were made.

## Files changed

- Eval domain/runtime: `src/opsmind/execution.py` and
  `src/opsmind/evals/{models,loader,evaluators,runner,persistence,repository,sqlite}.py`.
- API/runtime composition: `src/opsmind/api/{__init__,app,runtime,schemas}.py`.
- Existing public package exports and documentation: `src/opsmind/__init__.py`,
  `src/opsmind/agent/{__init__,graph}.py`, `README.md`, `docs/API.md`,
  `docs/ARCHITECTURE.md`, and `docs/DEVELOPMENT.md`.
- Golden artifact and governance: `evals/golden-v0.1.json`,
  `docs/adr/ADR-004-eval-runtime.md`, and this report/task artifact.
- Tests: `tests/test_eval_{api,evaluators,persistence,runner,suite}.py`.

## Validation evidence

The following results were verified by the main coordination session against
this task worktree before final handoff:

```text
Backend pytest         → 536 passed, 1 deselected
Ruff                   → PASS
Mypy                   → PASS
uv lock --check        → PASS; Resolved 55 packages
git diff --check       → PASS
Frontend npm test      → 22 passed
Frontend npm run lint  → PASS
Frontend npm run build → PASS
```

The frontend checks temporarily reused the already available `node_modules`
through a local symlink; the symlink was removed afterward and is absent from
the final git status. No dependency-lock changes were introduced.

This continuation did not run network access or `uv`; the lock result above is
the coordinator-verified result requested for this closeout.

## Live evaluation

- `DEEPSEEK_API_KEY`: `ABSENT` (presence checked without reading or recording
  the value).
- Result: `LIVE_EVAL_NOT_RUN`.

## Artifact and ADR completeness

- `tasks/active/TASK-P1-008-eval-runtime-and-golden-suite.md` contains the
  scoped goal, dependencies, in/out-of-scope constraints, acceptance criteria,
  required validation, and Developer handoff state. It remains `IN_PROGRESS`
  because independent Tester/Reviewer and the PM Architecture Gate are still
  pending.
- `docs/adr/ADR-004-eval-runtime.md` documents the shared execution boundary,
  safe evaluation observation, deterministic evaluator contract, persistence
  schema/transaction rules, API surface, consequences, and explicit
  non-goals. Its status remains `Proposed` pending the PM Architecture Gate.

## Known limitations and handoff

- Live DeepSeek evaluation is not available without the configured key.
- C01/C09/C12 expose the intentionally unimplemented knowledge, log-search,
  and conversation-persistence capabilities.
- Independent Tester, Reviewer, CI, and PM Architecture Gate remain pending.

The implementation is ready for independent Tester/Reviewer handoff. Merge
remains prohibited until the required governance gates pass.

## Post-Tester remediation addendum

The independent Tester report identified six MAJOR findings. They were
remediated on this Developer branch without changing the frozen Graph, Prompt,
model-routing, tools, Evidence, grounded-rendering, `READ_ONLY`, Run schema v1,
or existing API contracts. The remediation adds strict JSON equality,
canonical `TaskStatus` observation checks, evaluator-specific loader
validation with turn-index bounds, finite non-recursive suite-depth handling,
fail-closed run-reference verification, and safe FAILED fallback for terminal
eval persistence failure.

Details are recorded in
`tasks/review/TASK-P1-008-developer-remediation-report.md`. The original Tester
report remains unchanged and the branch remains unpushed and unmerged pending
independent retest and the PM Architecture Gate.
