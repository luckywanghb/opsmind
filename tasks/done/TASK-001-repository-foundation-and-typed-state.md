# TASK-001 — Repository foundation and typed state

## Status

```text
DONE
```

## Risk

```text
MEDIUM
```

## Owner role

```text
Developer
```

## Dependencies

- None

## 1. Goal

Create a testable Python repository foundation and implement the typed V0.1
`OpsAgentState` contract described by the architecture baseline.

## 2. Why this task exists

Every later Agent node, checkpoint, model gateway, and tool call needs a shared,
validated state contract.

## 3. In scope

- Python 3.11 `src/` package layout;
- project configuration for tests, linting, and type checking;
- enums for documented V0.1 taxonomies and actions;
- compact typed models for every top-level state section;
- validation that prevents unknown fields and invalid loop counters;
- unit tests for valid construction, schema rejection, and compact evidence.

## 4. Out of scope

- LangGraph graph construction;
- model-provider integration;
- prompts or business classification logic;
- tool registry and adapters;
- persistence and artifact-store implementations;
- Golden Case fixtures.

## 5. Required references

- `AGENTS.md`
- `docs/ARCHITECTURE.md` sections 3, 5, 6, 7, 11 and 12
- `docs/PRODUCT.md`

## 6. Input contract

The root state accepts the documented logical sections:

```text
identity, conversation, understanding, task, loop, facts, evidence,
decision, tool, safety, handoff, response
```

## 7. Output contract

An importable, provider-neutral `OpsAgentState` model whose nested public fields
are typed and whose enum values match the architecture baseline.

## 8. Required behavior

- reject unknown fields at every model boundary;
- reject negative loop counters and limits smaller than one;
- keep evidence compact by storing only summaries, key fields, metadata, and an
  optional artifact reference;
- default safety capability to `READ_ONLY`;
- avoid any runtime business routing.

## 9. Architecture constraints

- do not add direct model-provider clients;
- do not add business-rule `if/elif` routing;
- do not store raw tool output in state;
- do not change graph topology;
- keep concrete persistence and tool implementations out of this task.

## 10. Acceptance criteria

- [x] package imports on Python 3.11;
- [x] all documented top-level state sections exist and are typed;
- [x] documented intent, request-type, risk, and action values are represented;
- [x] extra fields and invalid counters fail validation;
- [x] safety defaults to `READ_ONLY`;
- [x] unit tests, lint, and type checks pass.

## 11. Test requirements

Developer tests:
- minimal valid state;
- full representative state;
- invalid enum and unexpected field;
- negative loop counter and zero limit;
- evidence with and without an artifact reference.

Tester should additionally consider:
- mutable-default isolation;
- invalid nested data;
- JSON serialization round trip;
- accidental raw-result field acceptance.

## 12. Validation commands

```bash
uv run pytest
uv run ruff check .
uv run mypy src
```

## 13. Deliverables

1. project configuration;
2. typed state module;
3. unit tests;
4. validation results;
5. tester and reviewer reports recorded in this task before completion.

## 14. Tester report

```text
PASS
```

- Tests added: exact architecture enum taxonomies; mutable-default isolation;
  malformed nested state; post-construction assignment validation; representative
  JSON round trip; non-finite number rejection across every JSON state field;
  mutation-boundary revalidation; key-name-agnostic per-item and aggregate evidence
  limits; and legal compact-payload compatibility.
- Failures found and resolved: non-finite timeout and JSON values initially broke
  JSON round trips, and an unbounded `EvidenceState.items` list allowed
  aggregate/container mutation bypass. Compactness is now enforced by deterministic
  structural and byte budgets rather than business-key naming policy.
- Boundary cases tested: negative, coercive, fractional, and non-finite loop
  numbers; nested `NaN`/infinity in all five JSON object fields; excessive strings,
  nesting, child collections, per-item size, evidence item count, and aggregate
  evidence size; mutation followed by boundary revalidation; manufacturing fields
  such as `raw_material_result`, compact `raw_result` / `raw_api_response`,
  `data_source`, and `log_reference`; the same business-key container mutated past
  its deterministic budget; optional artifacts; and unknown model fields.
- Regressions observed: none. Normal compact payloads, legal evidence boundaries,
  and typed JSON serialization round trips remain supported.
- Validation on Python 3.11.15: `uv run pytest` (68 passed),
  `uv run ruff check .` (passed), `uv run mypy src` (passed), and
  `uv lock --check` (passed).

## 15. Reviewer report

Decision:

```text
APPROVE
```

| Severity | Finding | Required action |
|---|---|---|
| BLOCKER | None | None |
| MAJOR | None | None |
| MINOR | None | None |
| NIT | None | None |

Final review confirmed that compact evidence is enforced through deterministic,
key-name-agnostic structural and byte budgets; all JSON state fields reject
non-finite numbers; mutation-boundary revalidation is documented; and the task
introduces no business routing, provider coupling, tool implementation, or
persistence implementation.
