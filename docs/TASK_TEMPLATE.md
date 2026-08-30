# OpsMind Development Task Template

Copy this file when creating a development task.

---

# TASK-[ID] — [Short title]

## Status

```text
BACKLOG | READY | IN_PROGRESS | TEST | REVIEW | DONE | BLOCKED
```

## Risk

```text
LOW | MEDIUM | HIGH
```

## Owner role

```text
Developer | Tester | Reviewer | PM/Architect
```

## Dependencies

- None

or:

- TASK-XXX
- TASK-YYY

---

# 1. Goal

State one concrete outcome.

Example:

> Implement the model-driven request-understanding node and its typed structured output.

---

# 2. Why this task exists

Explain what product or architecture capability it enables.

Keep this short.

---

# 3. In scope

- item
- item
- item

---

# 4. Out of scope

- item
- item
- item

Explicit non-goals prevent scope drift.

---

# 5. Required references

Read only the relevant sources.

Example:

- `AGENTS.md`
- `docs/ARCHITECTURE.md` sections 3, 5 and 6
- `docs/product-specs/golden-cases.md`

---

# 6. Input contract

Describe inputs precisely.

For Agent nodes include:
- state fields read;
- model profile;
- available context.

Example:

```text
Reads:
- conversation.current_query
- conversation.summary
- identity
- previous understanding when continuing a case
```

---

# 7. Output contract

Describe exact outputs.

Example:

```json
{
  "primary_intent": "...",
  "request_type": "...",
  "symptom": "...",
  "entities": {},
  "risk_signal": "...",
  "confidence": 0.0
}
```

Use real project schemas once they exist.

---

# 8. Required behavior

Describe behavior, not implementation details unless architecture requires them.

Example:
- classification must be model-driven;
- current and relevant prior context must be considered;
- exact Golden Case wording must not be hardcoded;
- invalid structured output must be handled.

---

# 9. Architecture constraints

Example:
- use Model Gateway;
- do not instantiate provider client directly;
- do not add business-rule `if/elif` routing;
- do not store raw tool results in state;
- do not change graph topology.

---

# 10. Acceptance criteria

Use verifiable criteria.

- [ ] criterion
- [ ] criterion
- [ ] criterion

Example:

- [ ] node returns typed structured output;
- [ ] invalid JSON/model output is handled without corrupting state;
- [ ] C01/C03/C05 intent tests pass;
- [ ] no direct DeepSeek/OpenAI client exists inside node;
- [ ] unit tests pass.

---

# 11. Test requirements

Developer tests:
- happy path;
- expected failure path.

Tester should additionally consider:
- malformed model output;
- missing state fields;
- ambiguous query;
- continued conversation;
- unexpected enum value;
- timeout;
- retry.

---

# 12. Validation commands

Example:

```bash
uv run pytest tests/unit/...
uv run ruff check .
uv run mypy ...
```

Only include commands actually configured by the repository.

---

# 13. Deliverables

Developer must report:

1. files changed;
2. implementation summary;
3. tests added;
4. validation results;
5. assumptions;
6. unresolved issues;
7. architecture conflicts, if any.

---

# 14. Tester report

```text
PASS | FAIL
```

Include:
- tests added;
- failures found;
- boundary cases tested;
- regressions observed.

---

# 15. Reviewer report

Decision:

```text
APPROVE | REQUEST_CHANGES | ESCALATE
```

Findings:

| Severity | Finding | Required action |
|---|---|---|
| BLOCKER/MAJOR/MINOR/NIT | ... | ... |

---

# 16. Escalation notes

Only if applicable.

Describe:
- what failed;
- attempts already made;
- competing options;
- decision required.
