# TASK-P1-008 — Reviewer Remediation Report

## Identity

- Task: `TASK-P1-008`
- Role: `Developer Reviewer Remediation`
- Branch: `task/TASK-P1-008-dev`
- Reviewer report: `tasks/review/TASK-P1-008-reviewer-report.md`
- Starting reviewed HEAD: `e33a75b`
- Merge/push: `PROHIBITED`

The independent Reviewer report remains unchanged. This report records the
four requested product remediations and the verification performed on the
Developer branch.

## Remediated findings

### MAJOR-1 — Import-order-safe shared execution boundary

`src/opsmind/evals/runner.py` no longer imports execution exceptions at module
import time. The service type remains available under `TYPE_CHECKING`, and the
runtime exception import occurs inside case execution after package
initialization. A fresh-process regression proves that direct
`from opsmind.execution import AgentExecutionService` succeeds.

### MAJOR-2 — Eval projection cannot fail a successful Chat run

`src/opsmind/execution.py` now projects each tool call through a bounded safe
helper. If eval JSON limits reject otherwise contract-valid tool arguments, the
observation receives an empty bounded argument object, an unavailable status,
and the typed `TOOL_ARGUMENTS_UNAVAILABLE` signal. If the aggregate eval
projection itself is unavailable, it falls back to a minimal typed observation
with `PROJECTION_UNAVAILABLE`. Neither path changes the public response or
the persisted AgentRun lifecycle; the evaluator turns the signal into a safe
assertion `ERROR`.

Regression coverage exercises both the shared execution service and
`POST /api/v1/chat` with a 600-character valid tool argument, and verifies the
durable run is `SUCCEEDED`.

### MAJOR-3 — Invalid evaluator returns are Case errors, not Job failures

`EvaluatorRegistry.evaluate` now validates the evaluator return model inside
the existing fail-closed `try` boundary. An exception or invalid result is a
safe assertion `ERROR`. A runner regression registers an evaluator returning
an invalid object and proves the resulting Job is `COMPLETED` with the Case
and assertion in `ERROR`, rather than a fatal Job failure.

The default evaluator test suite now covers all 18 registered evaluators with
PASS, quality-mismatch FAIL, and unavailable-observation ERROR paths. It also
covers a registered evaluator exception without exposing its private error
text. JSON comparison retains strict boolean-vs-number behavior while treating
JSON integers and floats as the same JSON number type, which matches the
typed `waiting_hours` contract.

### MAJOR-4 — Complete unreleased Golden truth assertions

`evals/golden-v0.1.json` remains suite version `0.1`; it is the still-unreleased
artifact and no released historical suite was modified. C06 now has a blocking
`request_type_in=["DIAGNOSE"]` assertion. C05 now has blocking structured
evidence assertions for `current_handler="U10108"` and `waiting_hours=4`.
The suite loader test verifies the exact blocking expectations, and wrong-value
tests prove each added C05/C06 truth assertion fails when its value is wrong.

## Scope guard

Only the shared execution/eval boundary, evaluator tests, Golden assertions,
and review reports changed for this remediation. Prompt text, Graph topology,
tool contracts and behavior, Evidence contracts, grounded rendering,
`READ_ONLY`, and Run schema v1 remain unchanged. The retained independent
adversarial test file was not removed, weakened, or skipped.

## Verification

All commands ran in `/Users/hongbo/vscode/agent/opsmind-p1-008` using the
existing shared Python environment:

```text
../opsmind-p1-007/.venv/bin/python -m pytest
→ 582 passed, 1 deselected, 1 pre-existing warning

../opsmind-p1-007/.venv/bin/ruff check .
→ PASS

../opsmind-p1-007/.venv/bin/python -m mypy src
→ Success: no issues found in 51 source files

git diff --check
→ PASS
```

The warning is the pre-existing Starlette `TestClient`/`httpx` deprecation
warning. No network access, `uv`, push, or merge was used.

## Handoff

All four Reviewer MAJOR findings are addressed locally with focused
regressions. The branch is ready for independent Reviewer re-entry; the PM
Architecture Gate remains separate and pending.
