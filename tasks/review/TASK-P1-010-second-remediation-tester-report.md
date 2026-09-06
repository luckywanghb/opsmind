# TASK-P1-010 Second Remediation Independent Tester Report

## Verdict

`PASS`

- BLOCKER: 0
- MAJOR: 0
- MINOR: 0
- NIT: 0

The Independent Tester gate is met for remediation candidate
`3595eaf613e06665588b2bdaa826d867a8080e45`.

## Reviewed identity and independence

- Base: `4d01d7c9995d86c91506e3d1f475050c113f75a3`
- Original Product HEAD: `f0f471414d10ddbce5e1f2edb4caec860ef3cde6`
- First remediation: `757ae77c0be9695fddd6ca5b86801bb28445bf67`
- Second remediation candidate: `3595eaf613e06665588b2bdaa826d867a8080e45`
- Draft PR: `#25`

I kept both prior FAIL reports unchanged, reread their attacks, inspected the
actual second-remediation diff, reran all existing independent attacks, and
added one test-only long-key truncation collision attack. Developer-reported
results and the separately reported remote CI success were not used as a
substitute for local independent execution.

## Remediation verification

### Case-variant identifier total order — PASS

The entity priority tuple now ends with the exact bounded key after its
case-folded form (`src/opsmind/conversations/service.py:88-100`). Therefore
`TARGET_ID` and `target_id` no longer have equal complete ranks.

At the 20-item boundary, the exact same candidate set containing 19 ordinary
identifier keys plus `TARGET_ID` and `target_id` yields identical checkpoints
in forward and reverse insertion order. The previous remediation finding is
closed.

Evidence:
`tests/test_p1_010_remediation_adversarial.py:134-153`.

### Over-256-character key collision — PASS

Current candidates retain the original unbounded key only for deterministic
collision resolution, sort by `(original.casefold(), original)`, and use
`setdefault` on the bounded 256-character storage key
(`src/opsmind/conversations/service.py:66-86`).

The independent attack uses two keys longer than 256 characters that truncate
to the same valid checkpoint key. Forward and reversed input maps both select
the lexically earlier original key's value:

```text
bounded stored key: identical 256-character prefix
winner: LEXICALLY-EARLIER
forward projection == reverse projection
```

Evidence:
`tests/test_p1_010_remediation_adversarial.py:156-177`.

### Oversized identity safe failure and transaction rollback — PASS

For a 513-character `source_context.user_id`:

```text
HTTP status: 503
error.code: CONVERSATION_PERSISTENCE_UNAVAILABLE
AgentRun lifecycle: FAILED
conversation_threads rows: 0
conversation_turns rows: 0
conversation_checkpoints rows: 0
```

The response does not contain the supplied oversized identity. No incomplete
conversation transaction remains.

Evidence:
`tests/test_p1_010_remediation_adversarial.py:65-98` and the original attack in
`tests/test_p1_010_independent_adversarial.py`.

### P0 identifier priority and historical retention — PASS

- The original full-budget `work_order_id` attack passes.
- A generic candidate set with `asset_id`, `incident_id`, and 30 non-ID fields
  retains both IDs and produces identical forward/reverse projections.
- A historical `asset_id` survives 40 current-turn non-ID fields, proving that
  current noise does not evict an older P0 continuity anchor.
- Source inspection found no C12, query-text, business-object, or fixture-value
  hardcoding in the retention implementation.

Evidence:

- `tests/test_p1_010_independent_adversarial.py`
- `tests/test_p1_010_remediation_adversarial.py:101-131`

## Focused attack result

```text
.venv/bin/python -m pytest -q \
  tests/test_p1_010_independent_adversarial.py \
  tests/test_p1_010_remediation_adversarial.py \
  tests/test_conversation_repository.py -vv

19 passed, 1 warning
```

This includes repository schema/version, isolation, concurrency, transaction
rollback, failed-run, and long-conversation budget coverage in addition to all
independent remediation attacks.

## Full validation

```text
.venv/bin/python -m pytest -q
617 passed, 1 deselected, 1 warning

.venv/bin/ruff check .
PASS

.venv/bin/mypy src
PASS — 56 source files

UV_CACHE_DIR=/tmp/... uv lock --check
PASS — 55 packages resolved

git diff --check
PASS

cd web && npm test -- --run
PASS — 41 tests

cd web && npm run lint
PASS

cd web && npm run build
PASS
```

The one backend warning is the existing Starlette/httpx deprecation warning.
The one deselected test is credential-gated. `DEEPSEEK_API_KEY` is absent, so
live-provider status remains `LIVE_EVAL_NOT_RUN`.

The parent task reports that remote Python and Web CI for second-remediation
SHA `3595eaf` also passed. This report's verdict is based on the independent
local evidence above.

## Tester changes

Added/updated only test and report artifacts:

- Added the long-key collision test to
  `tests/test_p1_010_remediation_adversarial.py`.
- Added `tasks/review/TASK-P1-010-second-remediation-tester-report.md`.

No product implementation was modified. Both earlier FAIL reports remain
unchanged.
