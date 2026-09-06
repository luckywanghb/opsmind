# TASK-P1-010 Remediation Independent Tester Report

## Verdict

`FAIL`

- BLOCKER: 0
- MAJOR: 1
- MINOR: 0
- NIT: 0

The original two MAJOR findings are fixed, but the remediation's required
order-independence is incomplete. Because `MAJOR != 0`, the Reviewer hard gate
is not met.

## Reviewed identity and method

- Base: `4d01d7c9995d86c91506e3d1f475050c113f75a3`
- Original Product HEAD: `f0f471414d10ddbce5e1f2edb4caec860ef3cde6`
- Remediation candidate HEAD: `757ae77c0be9695fddd6ca5b86801bb28445bf67`
- Draft PR: `#25`

I retained the first Tester report unchanged and independently reread it, the
two original adversarial tests, and the actual remediation diff from
`0136065` to `757ae77`. The Developer remediation report was not treated as
acceptance evidence. I added a separate test-only remediation attack file and
did not modify product implementation.

## Original finding retest

### Original MAJOR-1 — FIXED

The 513-character `source_context.user_id` attack now produces:

```text
HTTP status: 503
error.code: CONVERSATION_PERSISTENCE_UNAVAILABLE
AgentRun lifecycle: FAILED
conversation_threads rows: 0
conversation_turns rows: 0
conversation_checkpoints rows: 0
```

The response does not echo the oversized identity. Repository validation errors
are now normalized into the typed conversation persistence family at
`src/opsmind/conversations/sqlite.py:285-288`; the pre-existing execution
cleanup path consequently finalizes the already-started AgentRun as FAILED.
The conversation transaction rolls back without a thread, user turn, or
checkpoint residue.

Independent evidence:
`tests/test_p1_010_remediation_adversarial.py:65-98`.

### Original MAJOR-2 — FIXED for ordinary distinct keys

The original `work_order_id` attack passes. A separate generic test with
`asset_id` and `incident_id`, 30 non-ID fields, and forward/reversed input maps
also produces identical checkpoints and retains both IDs. No C12, exact query,
`work_order_id`, or fixture-value branch exists in the product remediation.

A historical `asset_id` also survives 40 current-turn non-ID noise fields,
proving that the new identifier priority is stronger than current-vs-historical
recency for different priority classes.

Independent evidence:

- `tests/test_p1_010_remediation_adversarial.py:101-118`
- `tests/test_p1_010_remediation_adversarial.py:121-131`

## New finding

### MAJOR-1 — Entity ranking still falls back to dict insertion order on valid case-variant keys

**Requirement violated:** the full-budget generic P0 identifier retention
strategy must be deterministic and independent of dictionary insertion order.

The ranking key is `(identifier class, source class, key.casefold())`
(`src/opsmind/conversations/service.py:78-89`). This is not a total order:
distinct valid keys such as `TARGET_ID` and `target_id` have the same complete
ranking tuple. Python's stable `sorted()` then retains their original mapping
order. At the 20-item boundary, the same candidate set therefore projects a
different P0 identifier depending only on insertion order.

Independent reproduction uses 19 ordinary identifier keys plus the two valid
case variants, then checkpoints the exact same candidates in forward and
reverse insertion order:

```text
forward checkpoint: retains TARGET_ID=UPPER-VALUE
reverse checkpoint: retains target_id=LOWER-VALUE
other 19 entries: identical
```

The failing test is
`tests/test_p1_010_remediation_adversarial.py:134-153`. This is within the
declared 20-item budget and uses generic identifiers, not C12 or a work-order
fixture. Provider/model JSON field order must not decide which continuation
anchor survives.

**Required remediation outcome:** establish a true deterministic total order or
an explicit canonicalization/collision policy for case-variant keys, and test
the same candidate set in multiple insertion orders. The solution must remain
generic and must not hardcode a case, entity type, or fixture.

## Validation evidence

Focused original attacks and repository remediation tests:

```text
.venv/bin/python -m pytest -q \
  tests/test_p1_010_independent_adversarial.py \
  tests/test_conversation_repository.py

14 passed
```

Independent remediation attacks excluding the new total-order attack:

```text
3 passed, 1 deselected
```

Full backend suite including all independent remediation attacks:

```text
1 failed, 615 passed, 1 deselected, 1 warning
```

The single failure is the new MAJOR above.

Other required gates:

```text
.venv/bin/ruff check .                         PASS
.venv/bin/mypy src                             PASS (56 source files)
UV_CACHE_DIR=/tmp/... uv lock --check          PASS
git diff --check                               PASS
cd web && npm test -- --run                    PASS (41 tests)
cd web && npm run lint                         PASS
cd web && npm run build                        PASS
```

`DEEPSEEK_API_KEY` is absent; live-provider status remains
`LIVE_EVAL_NOT_RUN`.

## Tester changes

Added only:

- `tests/test_p1_010_remediation_adversarial.py`
- `tasks/review/TASK-P1-010-remediation-tester-report.md`

The first Tester report was not modified. No product code was changed.
