# TASK-P1-009 INDEPENDENT TESTER

HEAD:

`95fee774b76f4bbc853951868cd2fcefac567f66`

Decision:

`PASS`

BLOCKER:

`0`

MAJOR:

`0`

MINOR:

`2`

- The frontend Eval decoder accepts a backend-invalid completed job whose
  `run_ids` contains the same ID twice when matching duplicate turn relations
  are supplied. The UI would render the same value for two turns. Backend
  Pydantic rejects duplicate case run IDs. This is defense-in-depth only and
  does not affect valid API data; full Pydantic cross-field invariant parity is
  explicitly not required by the PM spec.
- The frontend timestamp decoder accepts timezone-naive ISO-like timestamps.
  Backend Eval models require timezone-aware timestamps. The browser displays
  these as local time; valid persisted API data is timezone-aware. This is a
  strictness gap, not a data-loss or injection issue.

NIT:

`0`

Frontend:

- `npm test -- --run`: 4 files, 41 passed.
- `npm run lint`: PASS.
- `npm run build`: PASS.
- Existing frontend API/component tests cover valid, empty, malformed, error,
  lifecycle, quality, race, duplicate-click, safe-value, known-gap, and
  untrusted-text behavior.
- Independent temporary decoder probes reproduced the two MINOR findings
  above; the probe file was removed and no product code was changed.

Backend regression:

- `uv run --frozen pytest`: 590 passed, 1 deselected, 1 existing deprecation
  warning.
- `uv run --frozen ruff check .`: PASS.
- `uv run --frozen mypy src`: PASS (51 source files).
- `uv lock --check`: PASS (55 packages resolved).
- `git diff --check`: PASS.

Browser:

`PASS` — real Chrome browser against the root-coordinated FastAPI/Vite
services, with `OPSMIND_MODEL_PROVIDER=mock` and a fresh temporary persistent
SQLite store.

- Initial `/evaluation` showed the real header and truthful empty state; no
  `Demo fixture`, static `87.5%`, or `Planned` evaluation experience appeared.
- Clicking `运行 Golden Suite` created one persisted real job. The page showed
  job `2fadac11-f1f2-484d-a20c-2380d88e5280`, lifecycle `COMPLETED`, runtime
  `mock`, 8 cases, 0 PASS / 8 FAIL / 0 ERROR, 0.0% pass rate, and a real
  duration.
- C12 expansion showed `FAIL` together with `Known Gap`, complete assertion
  expected/actual/message fields, and ordered `Turn 1` / `Turn 2` run IDs.
- Browser double-clicking the run button created exactly one additional
  history entry (history changed from 1 to 2), supporting duplicate-run
  protection.
- Reloading `/evaluation` restored the same job ID and persisted case metrics
  from the temporary database.

Adversarial coverage:

- fake fallback: PASS — empty history stayed empty; no static metrics or
  fixture fallback; offline/network and server-safe error mapping covered by
  API tests.
- lifecycle/quality: PASS — COMPLETED quality is separate; STARTED/FAILED
  jobs show `N/A` and no fabricated cases; real browser showed COMPLETED with
  FAIL cases rather than green whole-job quality.
- malformed API: PASS for required basic shape/enum/count/array/string/value
  checks; the two non-blocking strictness gaps are listed as MINOR above.
- duplicate run: PASS — component test and real-browser double-click evidence.
- request race: PASS — independent component test prevents stale detail from
  replacing the current selection.
- HTML injection display: PASS — React text rendering and component coverage
  keep HTML-like runtime, known-gap, assertion-message, and safe values as
  text; no `dangerouslySetInnerHTML` is present.
- persistence refresh: PASS — real persisted job survived page reload.
- known gaps: PASS — C01/C09/C12 gaps remain visible; C12 remained `FAIL`, not
  reclassified as PASS or skipped.
- scope drift: PASS — no backend, prompt, model, Golden Suite, evaluator,
  persistence, or architecture changes; no Run Detail feature was added.

Developer remediation required:

`NO` for gate-blocking remediation. The two MINOR decoder strictness gaps are
reported for optional follow-up; they do not block this task under the PM
specification's explicit allowance against full Pydantic cross-field invariant
reimplementation.
