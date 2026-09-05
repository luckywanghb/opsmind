# TASK-P1-006 Final Independent Tester Report

## Verdict

**PASS — 0 BLOCKER, 0 MAJOR**

The final independent regression tested the exact immutable product HEAD
`318b93a8bcdcad6df06c41c0dee34f0daef7b9bb` on isolated branch
`task/TASK-P1-006-evidence-retest2`. Product code was not edited. This branch
adds strict test-only probes and this report.

Both earlier evidence reports and their probes were reviewed. The original six
Majors remain remediated, and the later Unicode format-control Major is fixed
generically. Browser, live-provider, push, merge, and reviewer actions were not
run, as instructed.

## Final Unicode `Cf` regression

The prior retest demonstrated U+202E RIGHT-TO-LEFT OVERRIDE, U+2066
LEFT-TO-RIGHT ISOLATE, and U+200B ZERO WIDTH SPACE passing through grounded
source values. Product HEAD now applies `unicodedata.category(character) ==
"Cf"` at the generic inert-text renderer boundary.

The final strict probes verify:

- every one of the 163 `Cf` code points in Python's Unicode 14.0.0 database is
  absent from rendered output and replaced by its explicit `\\uXXXX` form;
- broader families independently include U+00AD SOFT HYPHEN, U+061C ARABIC
  LETTER MARK, U+FEFF BOM/zero-width no-break space, U+FFF9 interlinear
  annotation, and supplementary-plane language/cancel tags;
- the three prior bidi/zero-width variants are included by the exhaustive
  category sweep; and
- ordinary Simplified Chinese plus English `work_order_query`, `APPROVING`,
  and `false` values retain their expected source-qualified presentation.

This confirms a category-generic fix rather than a three-code-point blacklist.

## Prior six-Major regression result

1. **Typed evidence schema validation — PASS.** Invalid result-status enum,
   string, number, and boolean values all fail closed with
   `EVIDENCE_FIELD_INVALID`. Nested typed traversal, strict no-coercion, whole
   payload validation, missing fields, undeclared fields, duplicate refs, and
   stable evidence IDs also pass the existing strict suites.
2. **Referenced NOT_FOUND — PASS.** An unreferenced not-found item cannot add
   an absence claim. Only a selected, typed `result_status=not_found` can
   support the specific not-found presentation.
3. **Untrusted source text — PASS.** Newlines, carriage returns, Markdown and
   claim-like delimiters are inert, and all runtime-supported Unicode `Cf`
   characters are encoded.
4. **Oversized tool output — PASS.** A custom typed adapter returning a
   3,000-character value raises bounded `MALFORMED_TOOL_RESULT` at the registry
   boundary.
5. **Frontend terminal outcomes — PASS.** `waiting_user` requires a nonblank
   clarification; `transferred` requires a nonblank reply or required handoff.
6. **Frontend strict response/evidence validation — PASS.** Unknown response
   and evidence keys, malformed/impossible timestamps, excessive depth/width,
   long strings, and oversized compact evidence are rejected. Valid leap-day,
   UTC, fractional, and offset timestamps pass.

## Independent safety and architecture audit

- **Fail-closed refs/schema/NOT_FOUND/compactness — PASS.** Reference identity,
  path grammar, declarations, typed values, null/missing values, duplicates,
  response compactness, and not-found provenance fail closed without partial
  factual rendering.
- **Frontend terminal/timestamp/unknown keys — PASS.** Strict probes cover the
  terminal outcome matrix, calendar/offset timestamp edges, allowlisted
  response/evidence shapes, and compact nested evidence.
- **Unsupported inference/threshold/false flags — PASS.** Durations, statuses,
  and `false` remain literal. Fixed limitation text does not convert them into
  SLA, timeout, workflow-progress, or universal-normality claims.
- **Permissions/incidents/unknown records — PASS.** Returned permission and
  incident fields remain source-qualified with entitlement, cause, scope, and
  remediation limitations. Unknown work orders, users/permissions, and
  incidents remain typed not-found results without invented facts.
- **Concurrency/no leakage — PASS.** Run-local registry copies, stable evidence
  IDs, detached metadata, concurrent graph/API runs, and provider concurrency
  remain isolated. Raw adapter payloads/messages, exception secrets,
  chain-of-thought, review prose, and decision goal/rationale do not enter the
  grounded final reply or public trace/UI presentation.
- **Model-first/no hardcode — PASS.** Source inspection found no fixture ID or
  D01-D03 routing in the graph and no intent-based tool branch. Fixture IDs
  remain only in synthetic data/tests/docs; selection and re-decision remain
  model-owned behind generic typed capabilities.
- **Read-only/failure/convergence — PASS.** Unknown tools/arguments, injected
  write capability, malformed adapter results, timeouts, retries, duplicate
  calls, tool/round limits, and terminal model failures retain bounded typed
  behavior.
- **No scope expansion — PASS.** Remediation is limited to generic evidence
  validation/rendering, compact tool results, frontend response validation,
  tests, and reports. It adds no write tool, persistence, RAG, integration,
  approval flow, or graph topology.

## Test-only artifacts

- `tests/test_p1_006_final_tester.py`: 17 strict backend cases, including the
  original four typed-value variants, NOT_FOUND, inert source text, oversized
  output, fail-closed refs, category-exhaustive Unicode `Cf`, representative
  `Cf` families, normal Chinese/English output, and no hardcoded routing.
- `web/src/api/final-evidence-tester.test.ts`: 19 strict frontend cases covering
  both terminal regressions, timestamp validity edges, unknown keys,
  compactness, and valid Chinese/English response preservation.

## Exact validation

```text
PYTHONPATH=<this-worktree>/src <frozen-sibling-venv>/bin/pytest -q tests/test_p1_006_final_tester.py
→ 17 passed

cd web && npm test -- --run src/api/final-evidence-tester.test.ts
→ 1 file passed; 19 tests passed

PYTHONPATH=<this-worktree>/src <frozen-sibling-venv>/bin/pytest -q
→ 472 passed, 1 deselected, 1 warning

PYTHONPATH=<this-worktree>/src <frozen-sibling-venv>/bin/pytest -q \
  tests/test_grounded_response_contract.py \
  tests/test_grounded_api_boundary.py \
  tests/test_p1_006_independent_adversarial.py \
  tests/test_structured_node_diagnostics.py \
  tests/test_tool_loop.py \
  tests/test_agent_kernel_tester_adversarial.py \
  tests/test_api_tester_adversarial.py
→ 149 passed, 1 warning

<frozen-sibling-venv>/bin/ruff check src tests
→ PASS

<frozen-sibling-venv>/bin/mypy src
→ Success: no issues found in 36 source files

UV_CACHE_DIR=/private/tmp/opsmind-p1-006-retest-uv-cache uv lock --check --offline
→ Resolved 55 packages; PASS

git diff --check
→ PASS

cd web && npm run lint
→ PASS

cd web && npm test -- --run
→ 5 files passed; 40 tests passed

cd web && npm run build
→ PASS
```

The sole backend warning is the existing Starlette `httpx` deprecation
warning. The existing opt-in live-provider test remains deselected. A direct
new-worktree `uv run` initially encountered a network-disabled cache miss; the
successful commands above used the sibling retest's already-frozen virtual
environment with this worktree explicitly first on `PYTHONPATH`, and lock
integrity was separately verified offline.

## Structured status

```json
{
  "task_id": "TASK-P1-006",
  "stage": "TEST",
  "verdict": "PASS",
  "product_head": "318b93a8bcdcad6df06c41c0dee34f0daef7b9bb",
  "branch": "task/TASK-P1-006-evidence-retest2",
  "blocker_count": 0,
  "major_count": 0,
  "browser_or_live_provider": "NOT_RUN_BY_INSTRUCTION",
  "pm_action": "REVIEW_READY"
}
```
