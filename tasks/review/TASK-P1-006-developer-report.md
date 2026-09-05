# TASK-P1-006 Developer Report

## Identity

- Task: TASK-P1-006 / GitHub Issue #16
- Role: Developer — Luna Max
- Branch: `task/TASK-P1-006-dev`
- Escalation remediation HEAD: `2b4b5360f4cbfca90d842df087922c46767a45a7`
- Base: `401422d307ce334616c01dfce6e0172eb2bb03a5`
- Stage: TEST → independent Tester / Reviewer
- Architecture impact: `ARCHITECTURE_CHANGE`
- PM action: `REVIEW_REQUIRED` (architecture gate remains)

## Outcome

- Replaced the two-node kernel with a generic bounded model-selected
  read-only tool loop and re-decision path.
- Added typed per-run registry/adapters for work orders, permissions, and
  incidents, with unknown records returning typed `not_found` evidence.
- Added model-backed selection/review/final/clarification/handoff nodes,
  compact evidence projection, actual safe trace/API fields, and localized UI
  rendering for completed tool/review/reply steps.
- Added source-field semantics and bilingual grounding constraints so duration,
  status, and boolean flags cannot be presented as unsupported SLA, progression,
  or general-normality conclusions.
- Applied the Architect remediation: latest advisory review state and
  run-local capability metadata now reach re-decision, review, and every
  terminal context; shared bounded-answer policy governs reply, clarification,
  and handoff without Python answer routing.
- Applied the escalation remediation without changing graph topology or
  business routing: model-facing review schemas retain nested JSON Schema
  structure, enums, references, `anyOf` branches and nullability; adapter
  outputs are checked for finite JSON inside tool execution and normalize to
  `MALFORMED_TOOL_RESULT`; structured model-node failures carry only an
  allowlisted node/schema/profile/category diagnostic for request-correlated
  internal logging while the public error envelope remains generic.
- Added detached registry metadata snapshots, a fixed bound for trace
  summaries, frontend evidence-metadata validation, and completed-response
  outcome consistency while preserving legitimate closed/no-reply responses.
- Added regression coverage for D01–D03 plus unseen IDs, invalid/unknown
  tools, read-only policy, adapter failure, limits, concurrency, and leakage.

## Validation evidence

Escalation remediation validation (from the task worktree):

```text
UV_CACHE_DIR=/private/tmp/opsmind-p1-006-uv-cache uv run --frozen pytest -q
→ 426 passed, 1 deselected, 1 warning

UV_CACHE_DIR=/private/tmp/opsmind-p1-006-uv-cache uv run --frozen pytest -q tests/test_p1_006_independent_adversarial.py tests/test_structured_node_diagnostics.py
→ 27 passed

UV_CACHE_DIR=/private/tmp/opsmind-p1-006-uv-cache uv run --frozen ruff check src tests
→ PASS

UV_CACHE_DIR=/private/tmp/opsmind-p1-006-uv-cache uv run --frozen mypy src
→ Success: no issues found in 35 source files

UV_CACHE_DIR=/private/tmp/opsmind-p1-006-uv-cache uv lock --check
→ PASS

git diff --check
→ PASS

cd web && npm run lint
→ PASS

cd web && npm run test -- --run
→ 3 files / 16 tests passed

cd web && npm run build
→ PASS
```

## Independent Tester remediation pass — 2026-09-05

The independent Tester ran product commit `afa2df9f7cccd9ef4ad646f8c8bbc75f4425fb33`
from `task/TASK-P1-006-evidence-test` (tester commit `2642891`) and reported
**FAIL — 0 BLOCKER, 6 MAJOR**. The immutable browser/live-provider checks were
not run by Tester instruction. All seven backend and four frontend expected
failures were migrated into strict product tests; no `xfail`/`it.fails`
markers remain in the product test suite.

Remediation applied on top of `afa2df9`:

- MAJOR-1: grounded references now validate the complete detached evidence
  payload through the registered Pydantic response model with strict JSON
  semantics, including nested models/arrays, enums, nullability, and extra
  fields. The review-only `message` field is intentionally excluded.
- MAJOR-2: `NOT_FOUND` is emitted only when a resolved reference explicitly
  selects a validated `result_status=not_found`; unrelated evidence cannot
  add an absence claim, and duplicated metadata status must agree.
- MAJOR-3: source values are rendered as inert data by encoding control,
  delimiter, and Markdown-significant characters while preserving the
  deterministic source-qualified format.
- MAJOR-4: the registry applies the canonical compact evidence budgets before
  returning an adapter result, converting oversized typed output to the
  existing `MALFORMED_TOOL_RESULT` boundary error.
- MAJOR-5: the frontend requires a non-empty final reply for `waiting_user`
  and either a required handoff or non-empty reply for `transferred`.
- MAJOR-6: the frontend now rejects malformed timestamps, undeclared fields,
  non-finite values, and evidence payloads exceeding collection, nesting,
  string, or serialized-byte limits.

Final deterministic validation for this remediation:

```text
UV_CACHE_DIR=/private/tmp/opsmind-p1-006-uv-cache uv run --frozen pytest -q -rxX
→ 452 passed, 1 deselected, 1 warning

UV_CACHE_DIR=/private/tmp/opsmind-p1-006-uv-cache uv run --frozen ruff check src tests
→ PASS

UV_CACHE_DIR=/private/tmp/opsmind-p1-006-uv-cache uv run --frozen mypy src
→ Success: no issues found in 36 source files

UV_CACHE_DIR=/private/tmp/opsmind-p1-006-uv-cache uv lock --check
→ Resolved 55 packages in 1ms; PASS

git diff --check
→ PASS

cd web && npm run lint
→ PASS

cd web && npm test -- --run
→ 4 files passed; 21 passed

cd web && npm run build
→ PASS
```

No blocker or major findings remain from the independent Tester report.
Browser and live-provider validation remain intentionally not run.

Run from the task worktree with the locked dependency environment:

```text
UV_CACHE_DIR=/private/tmp/opsmind-p1-006-uv-cache uv run --frozen pytest -q
→ 399 passed, 1 deselected, 1 warning

UV_CACHE_DIR=/private/tmp/opsmind-p1-006-uv-cache uv run --frozen pytest -q tests/test_tool_loop.py
→ 19 passed

UV_CACHE_DIR=/private/tmp/opsmind-p1-006-uv-cache uv run --frozen ruff check src tests
→ PASS

UV_CACHE_DIR=/private/tmp/opsmind-p1-006-uv-cache uv run --frozen mypy src
→ Success: no issues found in 34 source files

uv lock --check
→ PASS

git diff --check
→ PASS

cd web && npm run lint
→ PASS

cd web && npm run test -- --run
→ 3 files / 12 tests passed

cd web && npm run build
→ PASS
```

## Deterministic integration evidence

`tests/test_tool_loop.py` exercises the real graph with model fixtures for:

- D01 work order → selection → execution → review → re-decision → Chinese reply;
- D02 permission and D03 incident tool selection;
- unseen permission/work-order records → typed `not_found` and clarification;
- privileged write registration blocked before handler invocation;
- unknown tool and invalid arguments rejected before execution;
- adapter failure, retry accounting, max tool calls, and concurrent registry
  isolation;
- no adapter message/raw payload in canonical state or safe trace.

## Limitations / follow-up

- Opt-in DeepSeek live smoke and coordinated browser E2E require the configured
  `/private/tmp/opsmind-deepseek.5i7uOR/runtime.env` and reserved ports; no key
  or environment contents are recorded here.
- No persistence or authentication was added, so thread IDs remain request
  correlation only.
- PM Architecture Gate, independent Tester verdict, independent Reviewer
  verdict, and GitHub CI/PR checks remain pending.

## Decisions / deviations

- Removed the temporary legacy graph and mock-history removal accommodations
  after inspection: they preserved obsolete two-node fixtures rather than a
  supported public contract.
- Kept execution as a `HARNESS` trace event using the existing
  `TOOL_SELECTION` logical task enum; node names distinguish selection from
  execution and avoid introducing provider-routing semantics.
- Kept `evidence_sufficient` and `recommended_action` advisory: a fresh model
  action decision still owns control flow, including when its decision differs
  from the review recommendation.

## PM Architecture Amendment — Evidence-Bound User-Facing Output

The PM-authorized reliability amendment is implemented in new commits on this
branch. Terminal model calls now return only a typed
`GroundedResponsePlanOutput`: terminal/presentation intent, a bounded
limitation/clarification enum, and relevant `EvidenceReference` ID/path
pairs. The plan has no answer, claim, or factual prose field. Review projects
assign stable per-run `E1`, `E2`, ... IDs without mutating caller-owned
evidence.

Registered tools now expose typed `ToolFieldPresentation` metadata (localized
labels, units, value kind, and conservative semantic marker). The renderer
resolves every reference against the registered response schema and source
value, then emits deterministic source-qualified Simplified-Chinese text.
Fixed limitation templates cover absent cause, SLA/threshold, entitlement,
remediation, scope, and match evidence. Duration, status, and false source
flags remain literal source fields.

Unknown/duplicate IDs, undeclared or missing/null paths, extra plan fields,
and terminal-mode mismatches fail closed before any output is rendered. The
renderer never reads decision goal/rationale or review prose. Public trace and
the UI action section use deterministic action/status summaries; typed
decision goal/rationale remain control-plane response diagnostics only.

Implementation commit: `416225d` (`feat: add evidence-bound response
planning`). Test and fixture migration commit: `3c3a42f` (`test: migrate
terminal fixtures to grounded plans`). Both are descendants of the immutable
historical baseline `d9821a1`.

### Amendment validation

```text
UV_CACHE_DIR=/private/tmp/opsmind-p1-006-uv-cache uv run --frozen pytest -q tests/test_grounded_response_contract.py tests/test_grounded_api_boundary.py
→ 17 passed, 1 warning

UV_CACHE_DIR=/private/tmp/opsmind-p1-006-uv-cache uv run --frozen ruff check src tests
→ PASS

UV_CACHE_DIR=/private/tmp/opsmind-p1-006-uv-cache uv run --frozen mypy src
→ Success: no issues found in 36 source files
```

### Final Developer validation

The complete frozen validation was run from this task worktree before
handoff; no real DeepSeek or browser call was made:

```text
UV_CACHE_DIR=/private/tmp/opsmind-p1-006-uv-cache uv run --frozen pytest -q
→ 443 passed, 1 deselected, 1 warning

UV_CACHE_DIR=/private/tmp/opsmind-p1-006-uv-cache uv run --frozen ruff check src tests
→ PASS

UV_CACHE_DIR=/private/tmp/opsmind-p1-006-uv-cache uv run --frozen mypy src
→ Success: no issues found in 36 source files

UV_CACHE_DIR=/private/tmp/opsmind-p1-006-uv-cache uv lock --check
→ Resolved 55 packages in 1ms; PASS

git diff --check
→ PASS

cd web && npm run lint
→ PASS

cd web && npm test -- --run
→ 3 files / 16 tests passed

cd web && npm run build
→ PASS
```
