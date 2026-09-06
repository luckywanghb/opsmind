# TASK-P1-009 — Real Eval UI

## Status

`PM_FINAL_GATE/PENDING`

## Risk

`MEDIUM` — frontend integration over the accepted P1-008 Eval Runtime.

## Owner role

`Delivery Reporter`

## Control plane

- Issue: `#22`
- Draft PR: `#23` (`OPEN`, `DRAFT`)
- Branch: `task/TASK-P1-009-dev`
- Base: `3440130c741f311a436d76155a38e2d7a0fc7d74`
- Reviewed Product HEAD: `522f62a722e97fc9344f8d1abd64d7276e843c76`
- PM Final Gate: `PENDING`
- Merge: `PROHIBITED`

## Goal

Replace the `/evaluation` demo fixture with a truthful UI over the persisted
P1-008 Eval APIs. Users can run the official `opsmind-golden` suite, inspect
history and real metrics, distinguish lifecycle from quality, and inspect
cases, assertions, known gaps, runtime identity, and ordered run IDs.

## In scope

- Typed frontend Eval contracts and strict runtime response validation.
- `listEvals`, `getEval`, and `runEval` API client operations with safe errors.
- Initial newest-job selection, persisted history selection, and explicit run.
- Truthful empty, loading, `STARTED`, `FAILED`, and request-error states.
- Cases/pass/fail/error/pass-rate metrics only for completed job data.
- PASS/FAIL/ERROR case semantics, known gaps, assertions, safe values, timing,
  metadata, runtime identity, and ordered run IDs.
- Duplicate-run prevention and stale detail response protection.
- Frontend unit/component coverage and a real-browser integration run using
  FastAPI, Vite, the mock provider, and a temporary persistent database.
- Full backend and frontend regression validation.

## Out of scope / non-goals

- No backend, public API, Eval persistence, Golden Suite, evaluator, Agent,
  prompt, model, tool, or architecture change.
- No suite selector, prompt/model/provider input, case/assertion editor, run
  detail page, polling, worker, analytics/chart, RAG, log search, conversation
  persistence, write tool, auth, RBAC, or multi-tenant work.
- No fixture fallback, automatic eval, unsafe HTML rendering, or merge.

## Acceptance criteria

- The Evaluation page has zero dependency on `evaluationCases` and never shows
  the old static 8/7/1/87.5% or `Planned` experience.
- Page load calls only `GET /api/v1/evals?limit=20`; empty and failure states are
  truthful, and the newest persisted job is selected and fetched when present.
- Explicit run sends exactly one `POST /api/v1/evals/run` with
  `{ "suite_id": "opsmind-golden" }`, displays the returned job, and refreshes
  history without polling or a redundant detail request.
- Lifecycle is displayed independently from PASS/FAIL/ERROR quality;
  `runtime_identity` is prominent and known gaps never reclassify failures.
- Failed/started jobs do not fabricate final metrics or case results.
- API responses are structurally validated without unsafe contract casts;
  malformed/network/server errors map to safe Chinese UI messages.
- Rapid history selection cannot let a stale response overwrite the current
  choice, and a failed run preserves previously loaded data.
- Case detail renders assertion fields and safe values as bounded text, never
  executable HTML; run IDs retain backend order as Turn 1, Turn 2, etc.
- Required frontend/API/component adversarial tests pass.
- Real browser acceptance proves run creation, detail display, runtime identity,
  assertion/run-ID visibility, and persistence after refresh.
- Full frontend and backend regression commands pass; Tester gate is B0/M0 and
  Reviewer returns APPROVE B0/M0.

## Required validation

```bash
uv run --frozen pytest
uv run --frozen ruff check .
uv run --frozen mypy src
uv lock --check
git diff --check
cd web && npm test && npm run lint && npm run build
```

Browser acceptance uses `OPSMIND_MODEL_PROVIDER=mock` and a temporary
`OPSMIND_RUN_STORE_PATH`; it must not require DeepSeek credentials.

## Gate

Stop at `PM FINAL GATE`. The Draft PR must remain unmerged until the PM gives
explicit approval.
