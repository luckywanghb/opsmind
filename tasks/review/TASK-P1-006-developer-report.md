# TASK-P1-006 Developer Report

## Identity

- Task: TASK-P1-006 / GitHub Issue #16
- Role: Developer — Luna Max
- Branch: `task/TASK-P1-006-dev`
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
- Added regression coverage for D01–D03 plus unseen IDs, invalid/unknown
  tools, read-only policy, adapter failure, limits, concurrency, and leakage.

## Validation evidence

Run from the task worktree with the locked dependency environment:

```text
UV_CACHE_DIR=/private/tmp/opsmind-p1-006-uv-cache uv run --frozen pytest -q
→ 395 passed, 1 deselected, 1 warning

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
