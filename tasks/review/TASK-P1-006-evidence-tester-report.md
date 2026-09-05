# TASK-P1-006 Independent Tester Report

## Verdict

**FAIL — 0 BLOCKER, 6 MAJOR**

Tested the product implementation at `afa2df9f7cccd9ef4ad646f8c8bbc75f4425fb33`
on `task/TASK-P1-006-evidence-test`. Product code was not changed. The
independent probes are in `tests/test_p1_006_evidence_tester.py` and
`web/src/api/evidence-tester.test.ts`; known regressions are strict `xfail`
tests so the frozen suite remains executable while the contract failures stay
visible.

The checked-in task specification, ADR-002, architecture/kernel/API docs, the
Developer report, and the actual PR diff were reviewed. GitHub Issue #16 and
comment `5548925706` could not be fetched from this environment (DNS/network
failure); the checked-in task/ADR contain the same Evidence-Bound amendment
used for this audit. Browser and live-provider validation were intentionally
not run, per the Tester instruction; this is not counted as a blocker.

## Unresolved findings

### MAJOR-1 — Grounding does not validate evidence values against the typed response schema

`src/opsmind/agent/grounding.py:161-173` only asks the registry whether the
top-level field exists, while `:144-158` accepts any JSON scalar/collection.
The four independent probes in
`test_referenced_values_must_match_registered_response_schema` all render
instead of failing closed:

- `result_status="fabricated_status"` despite the registered enum;
- `status=123` despite a nullable string field;
- `waiting_hours="four"` despite a non-negative number/null field; and
- `abnormal="false"` despite a boolean/null field.

For example, the current renderer emits `来源 work_order_query：状态=123`.
This violates the requirement that a reference resolve against the registered
typed response schema before any factual REPLY output. Nested paths are also
only dictionary traversals, not schema traversals. The fix must validate the
selected payload/path recursively, including types, enums, nullability and
nested structures, before rendering.

### MAJOR-2 — `NOT_FOUND` can be asserted from an unreferenced evidence item

`src/opsmind/agent/grounding.py:365-371` scans all evidence items in addition
to resolved references. A plan citing found `E1.status` plus an unrelated
unreferenced `E2` with `metadata.result_status="not_found"` emits:

`来源 work_order_query：状态=APPROVING；该来源没有匹配记录，无法提供未返回的业务事实。`

The strict probe `test_not_found_presentation_must_be_supported_by_referenced_evidence`
fails this. `NOT_FOUND` must be supported by the referenced typed status (or a
separately explicit, validated not-found selection), never by unrelated run
state.

### MAJOR-3 — Untrusted source strings can inject surrounding final-reply text

`src/opsmind/agent/grounding.py:244-268` interpolates top-level strings with
`str(value)`; list scalar strings follow the same path at `:251-258`. A typed
status value containing `\n来源 attacker：状态=已修复\n**伪造**` is returned verbatim by
the renderer. The strict probe
`test_untrusted_source_strings_cannot_inject_surrounding_claims` fails because
the value creates a second source-looking line and markdown-looking block.

The final renderer contract requires hostile values to remain data without
being able to add surrounding claims. Control characters/formatting must be
encoded or otherwise rendered as inert data at this boundary. React text
nodes currently escape HTML, but the API renderer itself still returns the
unsafe string to other clients.

### MAJOR-4 — Oversized typed adapter output is not rejected at the tool boundary

`ToolRegistry.execute` (`src/opsmind/tools/registry.py:346-355`) validates the
response model and finite JSON, but does not apply compact evidence budgets.
An independent custom typed adapter returning a 3,000-character field is
accepted by `execute`. During review,
`src/opsmind/agent/nodes/review_tool_result.py:162-175` constructs
`EvidenceItem`, where the compact-size validator raises an uncaught Pydantic
`ValidationError` instead of the bounded `MALFORMED_TOOL_RESULT` path. The
strict probe `test_oversized_typed_adapter_output_is_rejected_at_tool_boundary`
records this regression.

This violates the malformed-result/fail-closed boundary and can turn a bad
adapter response into an unhandled request failure. Enforce compact bounds at
adapter normalization or catch projection validation and convert it to the
existing typed tool failure path.

### MAJOR-5 — Frontend accepts terminal statuses with no usable outcome

`web/src/api/opsmind.ts:44-50, :69-73` requires an outcome only for
`status === "completed"`; `waiting_user` and `transferred` responses with no
reply, evidence or handoff are accepted. The strict probes
`rejects a transferred response with no handoff or outcome` and
`rejects a waiting-user response with no clarification outcome` both fail.

`web/src/pages/ChatPage.tsx:122` then renders such payloads as a completed
analysis with no clarification or handoff result. Status-specific runtime
validation is required: waiting-user needs a non-empty clarification result,
transferred needs a required handoff or non-empty handoff reply, and closed
may remain empty.

### MAJOR-6 — Frontend response/evidence validation is not strict enough for its typed contract

`web/src/api/opsmind.ts:31-41` accepts any string as an evidence timestamp,
including `not-an-iso-timestamp`; `:53-83` also accepts undeclared top-level
fields such as an `answer` claim because it has no key allowlist. The strict
probes `rejects evidence with a malformed timestamp` and `rejects undeclared
top-level response fields` both fail. The current UI does not use `answer`, but
accepting it weakens the trust boundary and permits future code to expose an
unvalidated claim. Parse/validate the datetime shape and reject unknown
response/evidence fields (plus the declared compact limits where this client
boundary is responsible for them).

## Passing coverage / architecture audit

The independent and existing suites pass the following areas:

- `GroundedResponsePlanOutput` has no factual prose field and rejects extra
  fields; invalid IDs/paths, missing/null fields, duplicate references, max
  references, order, stable IDs, terminal mismatch, and no-partial-render
  behavior are covered.
- Built-in field presentation metadata is direct typed field meaning and does
  not encode D01 answer conclusions. Permission role/permission facts and
  incident facts retain their limitation wording; elapsed duration and
  `false` source flags remain literal.
- Decision goal/rationale, review prose, adapter messages, raw provider/tool
  payloads and chain-of-thought do not enter final grounding, safe trace, or
  the tested UI decision display. Model failures are sanitized and the trace
  is action/status-only.
- Registry/tool boundaries cover typed arguments/results, unknown tools,
  READ_ONLY policy, finite values, timeout/retry/round/tool-call limits,
  duplicate calls, concurrent registry/evidence isolation, and typed
  not-found results.
- Source search found no hardcoded `WO20260001`/`D01`/intent routing in the
  graph or runtime product logic. The identifiers remain in synthetic fixture
  data and tests/docs only.
- Chinese-input prompt/UI behavior and English enum/tool names are covered by
  the existing deterministic tests. No browser, real provider, key, or live
  runtime was used.

## Validation evidence

All required deterministic gates completed on this branch:

```text
UV_CACHE_DIR=/private/tmp/opsmind-p1-006-uv-cache uv run --frozen pytest -q -rxX
→ 447 passed, 1 deselected, 7 xfailed, 1 warning

UV_CACHE_DIR=/private/tmp/opsmind-p1-006-uv-cache uv run --frozen ruff check src tests
→ PASS

UV_CACHE_DIR=/private/tmp/opsmind-p1-006-uv-cache uv run --frozen mypy src
→ Success: no issues found in 36 source files

UV_CACHE_DIR=/private/tmp/opsmind-p1-006-uv-cache uv lock --check
→ PASS (55 packages resolved)

git diff --check
→ PASS

cd web && npm run lint
→ PASS

cd web && npm test -- --run
→ 4 files passed; 16 passed, 4 expected fail

cd web && npm run build
→ PASS
```

The seven backend xfails comprise four schema-value probes (MAJOR-1), one
mixed not-found probe (MAJOR-2), one injection probe (MAJOR-3), and one
oversized-result probe (MAJOR-4). The four frontend expected failures comprise
the two status-outcome probes (MAJOR-5) and the timestamp/unknown-field probes
(MAJOR-6).

## Structured status

```json
{
  "task_id": "TASK-P1-006",
  "stage": "TEST",
  "verdict": "FAIL",
  "product_head": "afa2df9f7cccd9ef4ad646f8c8bbc75f4425fb33",
  "branch": "task/TASK-P1-006-evidence-test",
  "blocker_count": 0,
  "major_count": 6,
  "browser_or_live_provider": "NOT_RUN_BY_INSTRUCTION",
  "pm_action": "REVIEW_REQUIRED"
}
```
