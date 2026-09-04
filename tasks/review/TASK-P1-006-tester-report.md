# TASK-P1-006 Independent Tester Report

## Verdict

**FAIL — do not approve this HEAD.** The deterministic harness passes its
existing coverage, but independent adversarial checks reproduce five backend
contract/isolation defects and three frontend response-state defects. The
coordinator's real-browser D01 run is also a release blocker: HTTP 502 with
request ID `24d3fd61-7e33-4854-9017-dcefa4df5b74`. Per the stop instruction, no
additional live-provider or browser request was made.

## Test identity and scope

- Branch: `task/TASK-P1-006-test`
- Tested HEAD: `a68454ae5bd5a29a60f988f31baa9d1e89f29e33`
- Scope checked: Issue #16/current comments, PR #17 implementation, the
  TASK-P1-006 specification and required architecture/API documents, the
  developer report, and the coordinator escalation/browser evidence.
- Product source was not changed. Added tests are independent and test-only:
  `tests/test_p1_006_independent_adversarial.py`,
  `web/src/api/opsmind.test.ts`, and `web/src/pages/ChatPage.test.tsx`.

## Reproduced findings

### BLOCKER B-1 — real browser D01 failed (coordinator evidence)

The fixed-budget browser run returned HTTP 502, `模型返回格式异常，请稍后重试。`,
for request `24d3fd61-7e33-4854-9017-dcefa4df5b74`. Evidence is in
`/private/tmp/task-p1-006-browser-report.md` and
`/private/tmp/task-p1-006-escalation.md`. This is not claimed as an independent
live reproduction: the authorized live retest budget was stopped. Overall
acceptance cannot be PASS while the required real-browser D01 remains failed.

### MAJOR M-1 — bounded review schema corrupts nested JSON Schema

`tests/test_p1_006_independent_adversarial.py::test_all_tool_review_schemas_preserve_nested_types_enums_and_nullability`
strictly XFAILs. `src/opsmind/tools/registry.py:265-283` replaces every value
at depth 4 with the string `schema-depth-limit`. The observed
`work_order_query` review schema has all three `ToolResultStatus.enum` values
changed to that sentinel, and `waiting_hours.anyOf` changed to two sentinel
strings instead of number/null schemas. This affects the model-facing review
contract for the default tools and can make structured review requests
semantically invalid.

### MAJOR M-2 — model action goal is exposed verbatim in the safe trace

`tests/test_p1_006_independent_adversarial.py::test_hidden_cot_in_model_goal_is_not_exposed_in_safe_trace`
strictly XFAILs. With model goal `CHAIN-OF-THOUGHT-PRIVATE-123`, the emitted
event is:

```text
{"node":"decide_action","summary":"REPLY: CHAIN-OF-THOUGHT-PRIVATE-123",...}
```

`src/opsmind/agent/graph.py:236-243` copies `decision.goal` into the event;
`src/opsmind/api/app.py:75-85` returns event summaries as the API trace. The
trace is described as safe/actual execution telemetry, so unredacted and
unbounded model text crosses that boundary.

### MAJOR M-3 — non-finite adapter output escapes as an uncaught graph error

Two strict XFAILs reproduce this at both boundaries:

- `test_tool_registry_does_not_accept_non_finite_tool_result_values`: a typed
  `waiting_hours=float("inf")` is accepted by
  `src/opsmind/tools/registry.py:253-257`.
- `test_non_finite_tool_result_becomes_bounded_failure_in_graph`: the same
  result reaches review and raises an uncaught Pydantic `ValidationError`:
  `ToolReviewContext.result: Value error, non-finite number at
  $.waiting_hours`.

The expected behavior is a bounded `MALFORMED_TOOL_RESULT`/handoff outcome;
the observed behavior is an exception escaping the agent run.

### MAJOR M-4 — completed response can render as completed with no outcome

`web/src/api/opsmind.test.ts::rejects a completed response that has no final
reply, evidence, or handoff` fails: `sendChat` accepts `status: "completed"`
with `final_reply: null`, `evidence: []`, and `handoff: null`. The UI regression
`web/src/pages/ChatPage.test.tsx::does not label a completed response as done
when no final response exists` also fails because
`web/src/pages/ChatPage.tsx:123` renders `已完成请求` from status alone. This is
a false-success state in the user-facing demo.

### MAJOR M-5 — frontend evidence validator accepts malformed metadata

`web/src/api/opsmind.test.ts::rejects malformed evidence metadata before
rendering` fails: an evidence item with `metadata: "private-detail"` is
accepted. `web/src/api/opsmind.ts:31-39` validates source/summary/key_fields/
artifact_ref/timestamp but never validates `metadata` as an object. The
client's runtime validator therefore does not enforce the backend evidence
contract before rendering.

### MAJOR M-6 — registry copy shares mutable tool metadata

`tests/test_p1_006_independent_adversarial.py::test_registry_copy_does_not_share_mutable_tool_metadata`
strictly XFAILs. `src/opsmind/tools/registry.py:259-262` copies the
`RegisteredTool` dataclass references without deep-copying its mutable
`ToolSpec`; changing `copied.get(name).spec.description` changes the source
registry's description. This violates the documented run-local capability
isolation guarantee. The separate concurrent runs test passes when each run
starts with a distinct registry.

## Checks that passed

Focused independent backend run:

```text
16 passed, 5 xfailed
```

Full backend suite (including the strict XFAIL regressions):

```text
415 passed, 1 deselected, 5 xfailed, 1 warning
```

The independent passing checks cover raised adapter failures, unknown tools and
wrong arguments, duplicate SEARCH, round/retry/timeout limits, unknown
incident IDs, no-tool END_CONVERSATION, Chinese context delivery, concurrent
state/registry separation, injection and privileged-write blocking, advisory
risk metadata, raw-provider leakage, and error-safe traces.

Static/frontend checks:

```text
ruff check src tests/test_p1_006_independent_adversarial.py   PASS
mypy src tests/test_p1_006_independent_adversarial.py         PASS
cd web && npm run lint                                      PASS
cd web && npm run build                                     PASS
cd web && npm run test -- --run                             3 failed, 13 passed
```

The stale-trace-after-error regression and existing error-state tests pass;
the three frontend failures are the two API contract tests and the false-
completed UI test listed above. The untracked temporary `web/node_modules`
dependency symlink used for this local test run was removed and is not part of
the tester changes.

The locked `uv run --frozen` invocation was unavailable in this isolated
worktree because its local cache lacked `hatchling` and package-index DNS was
unavailable. The equivalent checks above used the already-installed sibling
worktree environment; no dependency or product source was modified.

## Required disposition

Keep the task at **FAIL / review required**. Do not merge or spend another live
request budget on this tester branch. Resolve the schema projection, trace
boundary, non-finite adapter handling, registry deep-copy, and frontend
response-validation issues, then obtain the PM-directed real-browser retest
under a newly authorized budget.
