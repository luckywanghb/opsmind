TASK-P1-009 DEVELOPER REPORT

Base:
3440130c741f311a436d76155a38e2d7a0fc7d74
Product HEAD:
Final `task/TASK-P1-009-dev` commit; SHA is provided in the handoff.
Issue:
#22
Draft PR:
#23

Implementation:
- Eval API client: Added typed `listEvals`, `getEval`, and `runEval` calls for the real `/api/v1/evals` endpoints, with the official `opsmind-golden` suite and safe server/network error mapping.
- Runtime validation: Added bounded, fail-closed decoding for Eval summaries, jobs, cases, assertions, run links, enums, allowed keys, cross-field relations, and safe JSON values.
- Evaluation Page: Replaced the demo Evaluation page with a real API-backed page at `/evaluation`, including lifecycle state and runtime/build/job metadata.
- History: Loads the newest 20 persisted jobs, selects the newest job, supports refresh, and protects detail selection from stale request races.
- Metrics: Renders real case/pass/fail/error totals and pass rate only for completed jobs; non-terminal or failed jobs show `N/A` rather than fabricated quality metrics.
- Case details: Shows case ID, title, status, known-gap context, assertion count, and run count from the persisted job.
- Assertions: Shows blocking, status, expected, actual, and message fields with bounded safe-value rendering.
- Run IDs: Shows ordered `Turn 1`/`Turn 2` run IDs for multi-turn cases.
- Error/loading/empty: Added explicit initial loading, run loading/disabled, empty history, history-load, detail-load, run-failure, started, and failed-job states without fixture fallback.
- Fixture removal: Removed obsolete Evaluation demo fixtures and the stale Planned Capabilities evaluation test that asserted the old disabled UI.

Architecture changes:
NO

Backend product changes:
NO

Tests:
Frontend:
41 passed across 4 Vitest files; `npm run lint` PASS; `npm run build` PASS.
Backend:
`uv run --frozen pytest`: 590 passed, 1 deselected (1 existing deprecation warning).
Ruff:
PASS (`All checks passed!`).
Mypy:
PASS (`Success: no issues found in 51 source files`).
Lock:
PASS (`uv lock --check`, 55 packages resolved).
Diff check:
PASS (`git diff --check`).

Browser E2E:
PASS
Environment:
Real FastAPI with `OPSMIND_MODEL_PROVIDER=mock`, a temporary `OPSMIND_RUN_STORE_PATH`, real Vite, and the required real browser at `/evaluation`.
Scenario:
The initial page showed a truthful empty state with no `Demo fixture`, `87.5%`, or `Planned`. Clicking `运行 Golden Suite` showed `评测运行中…` and disabled the button. The real persisted job `c65b0ec2-9a94-43df-8957-9a60312c93fd` then appeared with runtime `mock`, 8 cases, 0 pass / 8 fail / 0 error, and 137 ms duration. A case expansion showed C12's Known Gap, ordered Turn 1/Turn 2 run IDs, and complete assertion expected/actual details. Reloading the page loaded the same job ID from persistence.

Known limitations:
The browser acceptance intentionally uses the deterministic mock provider, so the observed 0/8 quality result reflects the frozen Golden Suite capability gaps; no live DeepSeek evaluation was run. The UI exposes the official Golden Suite only and does not add suite editing, export, or deletion controls.

Scope intentionally not implemented:
No backend, Agent, prompt, Golden Suite, Eval runtime, persistence contract, API contract, or architecture changes; no new ADR; no LLM judge, arbitrary suite selector, or unrelated route redesign.
