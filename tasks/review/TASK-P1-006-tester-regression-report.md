# TASK-P1-006 Independent Tester Regression Report

## Verdict

**Deterministic retest: PASS. Overall acceptance: FAIL / not clearable.**

The remediation at `d9821a15620189dd3bb27892b69396321c828d0f` clears the
previously reproduced deterministic schema/registry/diagnostic/trace/UI
regressions in offline tests. Overall acceptance remains FAIL because the
required real-browser D01 acceptance is still blocked by the coordinator's
fixed-budget failure at the prior immutable HEAD; no live model, browser, key,
or port restart was authorized for this retest.

## Identity and scope

- Task: `TASK-P1-006`, Issue #16 / PR #17
- Tester branch: `task/TASK-P1-006-retest`
- Product HEAD: `d9821a15620189dd3bb27892b69396321c828d0f`
- Compared remediation range: `a68454ae5bd5a29a60f988f31baa9d1e89f29e33..d9821a15620189dd3bb27892b69396321c828d0f`
- Test-only additions in this branch: `tests/test_p1_006_retest_adversarial.py` and focused frontend regressions in `web/src/pages/ChatPage.test.tsx`.
- No product implementation was changed by this tester.

## Independent regression results

The existing independent adversarial suite and structured-node diagnostics
suite pass together: **210 passed**. The additional retest suite passes:
**11 passed**.

The checks cover the previously confirmed boundaries and the remediation
claims:

| Boundary | Result | Evidence |
| --- | --- | --- |
| Review schemas for work-order, permission and incident tools | PASS | Nested `anyOf`, enum literals, nullable fields, array item schemas, `$defs` and field structure remain intact; no depth sentinel replaces schema values. |
| Adapter malformed/raised/non-finite results | PASS | Results become bounded typed failures (`MALFORMED_TOOL_RESULT` or `TOOL_EXECUTION_FAILED`); private payload/exception text does not enter state or public output. |
| Registry ownership and concurrent isolation | PASS | Deep-copied registration metadata and run-local registries remain isolated under mutation and concurrent graph runs. |
| Unknown tool, wrong arguments, duplicate search, retry/round/timeout limits | PASS | Harness blocks before adapter execution and terminates within configured bounds. |
| Read-only and injection boundaries | PASS | Privileged write and injected extra arguments never reach a handler; advisory risk signals do not route away from an allowed read-only capability. |
| Chinese/context delivery and unknown IDs | PASS | Latest review facts, capability metadata, source fields and bounded policy reach the intended model contexts; unknown records remain typed `not_found` without fabricated fields. |
| Trace and raw/CoT boundary | PASS | Public trace contains only actual completed nodes, bounded summaries (500 characters), and no provider payload, prompt, exception or secret. The test does not treat an arbitrary prior CoT sentinel as proof of a leak. |
| Structured-node API diagnostics | PASS | All four structured nodes × schema-mismatch/invocation failures (8 cases) return generic 502 envelopes, and log only request ID, node, expected schema, logical profile and sanitized category. A private/unallowlisted category is normalized. |
| Frontend metadata/completed/stale/error behavior | PASS | Evidence metadata is validated; false-completed responses are not labeled complete; legitimate closed/no-reply responses remain accepted; a failed later request clears the previous trace. |

The new diagnostics tests specifically assert exact node attribution for
`understand_request`, `decide_action`, `select_tool` and
`review_tool_result`, with no raw error/query text in either response or the
allowlisted log record. The new trace tests assert actual node order and the
500-character bound.

## Validation commands

Using the existing locked project virtual environment available in the sibling
worktree (the sandbox could not hydrate a fresh `uv run --frozen` environment):

```text
PYTHONPATH=src ../opsmind/.venv/bin/pytest -q -rxX
→ 437 passed, 1 deselected, 1 warning

../opsmind/.venv/bin/ruff check src tests
→ All checks passed

../opsmind/.venv/bin/mypy src
→ Success: no issues found in 35 source files

UV_CACHE_DIR=/private/tmp/opsmind-p1-006-uv-cache uv lock --check
→ Resolved 55 packages in 1ms

git diff --check
→ PASS

cd web && npm run test -- --run
→ 3 files / 18 tests passed

cd web && npm run lint
→ PASS

cd web && npm run build
→ PASS
```

The initial fresh `uv run --frozen` attempt was blocked by the sandbox's
uncached build dependency and unavailable package-network access; it did not
alter product files. The direct locked sibling environment and all static,
lock, diff and frontend validations above completed successfully.

## Remaining blocker

**B-1 — BLOCKER for overall acceptance: real-browser D01 remains failed and
has no authorized retest.** The coordinator artifact
`/private/tmp/task-p1-006-browser-report.md` records the first exact D01 request
on `a68454ae5bd5a29a60f988f31baa9d1e89f29e33` returning HTTP 502 / UI message
`模型返回格式异常，请稍后重试。`, request ID
`24d3fd61-7e33-4854-9017-dcefa4df5b74`; the second predeclared request was not
run under the stop-on-first-failure rule. This tester did not repeat that live
request, per the stopped escalation budget. Deterministic tests therefore do
not prove that the current real DeepSeek/browser path satisfies D01.

No new deterministic Blocker or Major was reproduced at the current HEAD. The
prior schema projection defect, unsafe failure attribution/leakage boundary,
non-finite adapter boundary, registry aliasing risk, trace bound, and frontend
response guards all pass the independent retest. The previous grounding issue
and clarification behavior remain historical browser evidence; this report
does not claim a live-model fix without an authorized run.

## Tester recommendation

Keep the task at **REVIEW / PM decision required**, with no merge or
`READY_TO_MERGE` status. A future PM decision must explicitly authorize any
new real-browser/model diagnostic budget before live validation; if authorized,
repeat only the predeclared acceptance procedure on a fresh immutable HEAD and
retain the failure artifact if the first request fails.
