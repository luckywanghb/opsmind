# TASK-P1-011 Astra Low Reviewer Report

Decision: **APPROVE**

- BLOCKER: 0
- MAJOR: 0
- MINOR: 1
- NIT: 0

Reviewer: `gpt-6-astra`, reasoning effort `low`, per the explicit user override recorded in the task. This supersedes the original Astra Medium label.

## Reviewed identity

- Reviewed Base: `ac003587d036b22ff43adee69d93e9f43eb90183`
- Reviewed Product HEAD: `aa278f024cd6e0aa6b5720db732325d3cdf7b153`
- Reviewed Evidence HEAD: `bfe73a3d25aba8873773542147fc798cb0ea2c74`
- Reviewed HEAD (including Tester report): `ef286678d4ddda3def196ccbf07b6e7c321a9300`
- Branch: `task/TASK-P1-011-dev`

The Product-to-Reviewed diff contains reports and Tester-only fixtures/tests. This review does not cover subsequent product changes. Only this report was added by the Reviewer; product code and tests were not modified.

## Architecture

Independently inspected AGENTS.md, task requirements, ADR-006, architecture/product/workflow guidance, actual Base-to-Product diff, implementation, and runtime paths. Knowledge is registered through the existing `RegisteredTool`, `ToolSpec`, typed request/response, and READ_ONLY registry. Repository, cleaning/chunking, lexical ranking, and tool adapter are separated. No graph node or edge, Agent state semantics, conversation restore semantics, grounding trust model, dependency, frontend, or API implementation was changed. No alternate RAG context path, write capability, embedding service, connector, knowledge admin API/UI, or log search was introduced. ADR status correctly retains the PM gate.

## Retrieval and bounds

The four versioned synthetic documents cover closure, ledger export, permission application, and QualityHub report export. Loader validation covers schema/status, duplicate IDs, UTF-8/content, bounds, missing files and path traversal/symlink escape; ingestion errors expose a generic code. Only active documents are chunked. NFKC/line-ending/whitespace cleaning retains prerequisites and warnings. Fixed 1,000-character windows with 200-character overlap and stable offset-based IDs are deterministic. The response excerpt limit is 1,200 characters, below the task's 2,000-character maximum.

Ranking uses generic normalized Latin/identifier and Chinese bigram lexical features with BM25-style scores, scoped before ranking, and stable document/chunk tie breaking. Query/case hardcodes were not found in product search code. Typed no-match results carry no fabricated provenance, and FOUND requires all provenance/excerpt fields. The lexical overlap heuristic is limited and cannot establish semantic relevance for every paraphrase; that is within the explicitly accepted first-version limitations.

## Evidence, grounding, and continuation

Inspected `review_tool_result`, typed response revalidation and field resolution in `grounding.py`, and conversation `initial_state`/checkpoint construction. The review payload comes from the actual tool response, excludes adapter `message`, and becomes current-run evidence; review prose is not used as source field data. Final facts are resolved from registered typed fields by the unchanged renderer. No source file path exists in the knowledge response schema. Only the selected chunk reaches review/evidence, as also exercised by the multi-chunk sentinel integration test.

The conversation service constructs fresh state without restored evidence. Existing two-run integration coverage executes knowledge search again, preserves thread identity, produces new request/run IDs, and records fresh evidence. Independent negative probes additionally confirmed forged review prose does not enter public evidence or final facts, and a nonexistent E99 citation fails closed with HTTP 502 rather than producing knowledge prose.

## Eval and regression

Golden v0.3 C01/C13 require SEARCH, real knowledge tool use, FOUND, K001/K002 respectively, source evidence, and nonempty reply. The integration endpoint exercises the shared execution/runtime path; no eval-specific knowledge injection exists. The new action-occurrence evaluator is generic. Byte comparison confirmed Golden v0.2 unchanged. JSON comparison confirmed C03, C05, C12, C10, and C09 entries are unchanged in v0.3, preserving their live-data routing requirements and `LOG_SEARCH_NOT_IMPLEMENTED` gap.

Independent focused validation passed **151 tests**, including knowledge, adversarial corpus/routing checks, real FastAPI/Eval integration, grounding contracts/API boundaries, and conversation integration:

```bash
.venv/bin/pytest -q tests/test_knowledge.py tests/test_knowledge_integration.py tests/test_p1_011_tester_adversarial.py tests/test_grounded_response_contract.py tests/test_grounded_api_boundary.py tests/test_conversation_integration.py tests/test_eval_suite.py tests/test_eval_evaluators.py
# 151 passed, 1 existing Starlette/httpx deprecation warning

git diff --exit-code ac003587 aa278f0 -- evals/golden-v0.2.json src/opsmind/agent src/opsmind/conversations pyproject.toml uv.lock web
# no differences

git diff --check
# PASS
```

Additional independent Python/FastAPI probes used the real default registry with queued model decisions to replace review summary/confirmed facts with `FORGED_REVIEW_FACT` and response references with E99. The former retained K002 source fields and excluded the marker from evidence/final reply; the latter failed closed. A response-status matrix rejected `insufficient_evidence`, `denied`, and `error` as knowledge response statuses. These were ephemeral probes, not committed test changes.

The Tester reports 683 backend and 41 frontend tests passing, plus lint/type/build/lock checks. I inspected the actual independent tests and test-only browser server: it queues model outputs but instantiates real FastAPI, runtime, repository and knowledge registry, rather than returning a canned browser answer. The documented real Vite browser result includes HTTP 200 and persisted run `e99ff36b-4445-4ff3-9b0f-81dce4ec5107` with K001 provenance. Browser interaction and the complete backend/frontend suites were Tester evidence, not independently repeated by this Reviewer.

The current environment has no `DEEPSEEK_API_KEY` (presence-only check): **LIVE_EVAL_NOT_RUN**. Mock routing checks demonstrate harness/tool behavior under scripted selections, not live model semantic tool-selection accuracy. No live quality PASS is claimed. Exact final HEAD CI remains the root delivery workflow's responsibility.

## Findings

### MINOR-1 — Valid ISO timestamps with explicit offsets are rejected

Location: `src/opsmind/knowledge/models.py:23`.

`validate_updated_at` unconditionally appends `+00:00` after stripping a terminal `Z`. A valid value such as `2026-09-07T12:00:00+08:00` therefore becomes a string with two offsets and fails validation. This also affects `+00:00` timestamps and both metadata and tool-response validation. The documented ISO datetime contract should accept these standard forms.

Reproduction:

```bash
.venv/bin/python - <<'PY'
from opsmind.knowledge.models import validate_updated_at
for value in ('2026-09-07', '2026-09-07T12:00:00Z',
              '2026-09-07T12:00:00+08:00', '2026-09-07T12:00:00+00:00'):
    try:
        validate_updated_at(value)
        print(value, 'accepted')
    except ValueError:
        print(value, 'rejected')
PY
```

Observed: date and Z forms accepted; both explicit-offset forms rejected. Suggested follow-up: normalize only an actual terminal Z, otherwise pass the unchanged datetime string to `datetime.fromisoformat`, with offset-form coverage. This is nonblocking because the shipped repository-owned corpus uses valid date-only values, no runtime ingestion API exists, and invalid inputs fail closed without leakage.

## Gate

PM Architecture Gate: **PENDING**

Merge: **PROHIBITED**

Reviewer approval is the independent quality verdict, not PM architecture approval or merge authorization.
