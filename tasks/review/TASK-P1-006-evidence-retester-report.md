# TASK-P1-006 Independent Evidence Retester Report

## Verdict

**FAIL — 0 BLOCKER, 1 MAJOR**

The product was tested at the exact immutable HEAD
`593e89c1563e039155f934467ccc75ba3ce57258` on the isolated branch
`task/TASK-P1-006-evidence-retest`. Product implementation was not edited.
The retest added only strict test probes and this report.

The six findings in the prior independent Tester report are remediated by this
HEAD. One broader inert-data probe found a remaining Unicode format-control
injection at the deterministic grounded-rendering boundary. Browser, live
provider, push, and merge actions were not run, as instructed.

## Unresolved finding

### MAJOR-1 — Unicode format controls remain active in grounded source values

`src/opsmind/agent/grounding.py:317-343` escapes C0/C1 controls, newlines,
U+2028/U+2029, and Markdown delimiters, but passes other Unicode `Cf` format
controls through unchanged. Independent strict probes at
`tests/test_p1_006_evidence_retester.py:141-156` demonstrate this for:

- U+202E RIGHT-TO-LEFT OVERRIDE, which can visually reorder following text;
- U+2066 LEFT-TO-RIGHT ISOLATE, which changes bidirectional rendering; and
- U+200B ZERO WIDTH SPACE, which invisibly alters the displayed value.

All three are returned verbatim inside the source-qualified fact instead of
being encoded as inert `\\uXXXX` data. This leaves the same trust boundary
partially open after the prior newline/Markdown injection remediation: a
syntactically typed source string can still alter or conceal its visual
presentation. The three failures are one root cause and count as one Major.

The renderer should encode Unicode format controls (at least all `Cf`
characters, with an explicit allowlist only if a demonstrated source value
requires one) before returning user-facing text. This is bounded remediation
inside the existing generic renderer and requires no routing or architecture
change.

## Prior six-major remediation retest

1. **Typed evidence values — PASS.** The four original strict probes now reject
   invalid enum, string, numeric, and boolean values with
   `EVIDENCE_FIELD_INVALID`. New custom nested-model/list probes confirm typed
   traversal, index bounds, strict no-coercion, and whole-payload validation of
   an invalid field even when that field is not referenced.
2. **Referenced `NOT_FOUND` — PASS.** An unrelated unreferenced not-found item
   cannot add an absence claim. Only a selected, schema-validated
   `result_status=not_found` supports that presentation, and mismatched duplicate
   status metadata fails closed.
3. **Newline/Markdown string injection — PASS for the original case.** Newlines,
   source-looking delimiters, Markdown markers, links, and control delimiters
   are encoded. The Unicode `Cf` extension above remains a Major.
4. **Oversized adapter output — PASS.** A custom typed adapter returning a
   3,000-character value is rejected at `ToolRegistry.execute` as
   `MALFORMED_TOOL_RESULT`.
5. **Frontend terminal outcomes — PASS.** `waiting_user` requires a nonblank
   clarification reply; `transferred` requires a nonblank reply or required
   handoff.
6. **Frontend strict response/evidence validation — PASS.** Undeclared response
   and evidence fields, malformed/impossible dates and offsets, over-depth and
   over-width collections, long strings, oversized payloads, and malformed
   timestamps are rejected. Valid leap-day, UTC, fractional, and offset forms
   pass.

## Broader architecture and safety audit

- **Unsupported inference / threshold / false flags — PASS.** Source duration,
  status, and `false` flags remain literal; the fixed limitations do not turn
  them into SLA, timeout, workflow-progression, or universal-normality claims.
- **Permission and incident facts — PASS.** Generic typed presentation metadata
  renders only returned role/permission and incident fields and preserves the
  entitlement, scope, cause, and remediation limitations.
- **Unknown records and not-found — PASS.** Unknown work-order, permission, and
  incident identifiers remain typed not-found results without invented fields.
- **Concurrency and isolation — PASS.** Stable evidence IDs, registry copies,
  detached metadata, and concurrent custom graph runs remain isolated.
- **Raw / chain-of-thought / goal / rationale leakage — PASS.** Raw adapter
  results and adapter messages remain transient; structured failures are
  sanitized. Terminal plan context omits decision goal/rationale and review
  prose, and the renderer consumes only resolved typed references. Public trace
  and the tested UI show deterministic action/status summaries rather than
  goal/rationale or model reasoning. The API retains typed goal/rationale as
  control-plane diagnostics but the final grounded response does not use or
  render them.
- **Model-first / no hardcoding — PASS.** Source inspection found no D01 or
  `WO20260001` route and no intent-based tool branch in the graph. Selection and
  re-decision remain model-owned behind generic typed capabilities.
- **Read-only / convergence / failures — PASS.** Unknown tools and arguments,
  write-capability injection, adapter errors, malformed results, timeouts,
  duplicate calls, round/tool/retry limits, and sanitized failures retain their
  deterministic boundaries.
- **No scope expansion — PASS.** The remediation commit changes only evidence
  validation/rendering, adapter compactness validation, frontend response
  validation, strict tests, and the Developer report. It adds no capability,
  persistence, RAG, integration, write action, or graph topology.

## Test artifacts

- `tests/test_p1_006_evidence_retester.py`: 14 strict backend probes, including
  the seven prior backend regressions and new nested/list/no-coercion,
  unreferenced-invalid-field, inert-string, and generic source-audit checks.
- `web/src/api/evidence-retester.test.ts`: 18 strict frontend probes, including
  the four prior frontend regressions plus timestamp edges, nested compactness,
  list bounds, and undeclared raw-result checks.

## Exact validation

```text
UV_CACHE_DIR=/private/tmp/opsmind-p1-006-retest-uv-cache uv run --frozen pytest -q tests/test_p1_006_evidence_retester.py
→ FAIL: 3 failed, 11 passed
  (the three variants are one Unicode format-control root cause)

UV_CACHE_DIR=/private/tmp/opsmind-p1-006-retest-uv-cache uv run --frozen pytest -q
→ FAIL: 3 failed, 463 passed, 1 deselected, 1 warning

UV_CACHE_DIR=/private/tmp/opsmind-p1-006-retest-uv-cache uv run --frozen pytest -q --ignore=tests/test_p1_006_evidence_retester.py
→ 452 passed, 1 deselected, 1 warning

UV_CACHE_DIR=/private/tmp/opsmind-p1-006-retest-uv-cache uv run --frozen pytest -q tests/test_grounded_response_contract.py tests/test_grounded_api_boundary.py tests/test_p1_006_independent_adversarial.py tests/test_structured_node_diagnostics.py tests/test_tool_loop.py
→ 72 passed, 1 warning

UV_CACHE_DIR=/private/tmp/opsmind-p1-006-retest-uv-cache uv run --frozen ruff check src tests
→ PASS

UV_CACHE_DIR=/private/tmp/opsmind-p1-006-retest-uv-cache uv run --frozen mypy src
→ Success: no issues found in 36 source files

UV_CACHE_DIR=/private/tmp/opsmind-p1-006-retest-uv-cache uv lock --check
→ Resolved 55 packages; PASS

git diff --check
→ PASS

cd web && npm run lint
→ PASS

cd web && npm test -- --run
→ 5 files passed; 39 tests passed

cd web && npm run build
→ PASS
```

The sole warning is the existing Starlette `httpx` deprecation warning. The
existing opt-in live-provider test remains deselected.

## Structured status

```json
{
  "task_id": "TASK-P1-006",
  "stage": "TEST",
  "verdict": "FAIL",
  "product_head": "593e89c1563e039155f934467ccc75ba3ce57258",
  "branch": "task/TASK-P1-006-evidence-retest",
  "blocker_count": 0,
  "major_count": 1,
  "browser_or_live_provider": "NOT_RUN_BY_INSTRUCTION",
  "pm_action": "REMEDIATION_REQUIRED"
}
```
