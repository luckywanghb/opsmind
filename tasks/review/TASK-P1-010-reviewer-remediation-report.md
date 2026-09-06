# TASK-P1-010 Reviewer Remediation Report

## Decision

`REMEDIATION COMPLETE — READY FOR INDEPENDENT RE-REVIEW`

## Identity

- Reviewer-reviewed HEAD: `a1ebf1fbefa7d9e67adfb6214501eb8944e42216`
- Reviewer remediation Product HEAD:
  `e8cafa4550224cfe366219fc5ef2d0dfd71a771e`
- Draft PR: `#25`

## Reviewer findings addressed

### MAJOR-1 — current unresolved blocker at a full budget

Unresolved questions now use a dedicated bounded-recency projection. It walks
from newest to oldest, retains the 20 most recent unique bounded P0 items, then
returns them in chronological display order. A current review blocker appended
after 20 restored historical questions therefore survives and the oldest item
is evicted.

### MAJOR-2 — safe site scope continuity

`ConversationCheckpoint` now has a typed, 512-character `site_id`. A successful
run checkpoints explicit allowlisted site scope; a later fresh run restores it
into `IdentityState`, allowlisted `source_context`, and deterministic important
entities when the caller omits it. A later different explicit site raises
`ConversationIdentityConflictError`, causing the active conversation claim and
AgentRun to fail closed rather than silently changing scope.

The explicit identity value is authoritative if model-inferred entities claim
a different `site_id`. No arbitrary prior source-context field is retained.

### MINOR-1 — API limitations text

The obsolete statement that conversation checkpoints/thread continuation and
the Eval UI do not exist was removed. The document now distinguishes typed
application-level conversation continuity from out-of-scope LangGraph
execution resume and Chat history UI.

### NIT-1 — OpenAPI 409 declaration

The Chat operation now declares the shared `ErrorResponse` for HTTP 409, with
a regression assertion against generated OpenAPI.

## Verification

- Reviewer-only reproductions plus all conversation attacks/repository tests:
  `23 passed`.
- API/repository/reviewer focused suite: `41 passed`.
- Full backend: `621 passed`, `1 deselected`, one existing dependency warning.
- Ruff: PASS.
- Mypy: PASS (`56` source files).
- `uv lock --check`: PASS.
- `git diff --check`: PASS.
- Frontend Vitest: `41 passed`; lint PASS; production build PASS.
- Live DeepSeek: `LIVE_EVAL_NOT_RUN` because `DEEPSEEK_API_KEY` is absent.

Developer does not self-approve. Independent Reviewer re-review, CI on the
exact re-reviewed HEAD, and the PM Architecture Gate remain required. Draft
PR #25 must not be merged or converted to Ready before those gates.
