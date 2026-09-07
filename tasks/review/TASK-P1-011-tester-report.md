# TASK-P1-011 Independent Tester Report

## Verdict

`PASS`

- BLOCKER: 0
- MAJOR: 0
- MINOR: 0
- NIT: 0

The independent Tester entry gate is met. No product finding was identified.

## Reviewed identity

- Base: `ac003587d036b22ff43adee69d93e9f43eb90183`
- Product HEAD: `aa278f024cd6e0aa6b5720db732325d3cdf7b153`
- Tester Evidence HEAD: `bfe73a3d25aba8873773542147fc798cb0ea2c74`
- Current branch: `task/TASK-P1-011-dev`
- Product-to-evidence diff: the existing Developer report plus the two Tester-only test files; no product implementation or task/ADR file was modified.

I independently read `AGENTS.md`, the active TASK-P1-011 specification, ADR-006, the actual Base-to-Product diff, and the retrieval, tool, grounding, run, API, and frontend runtime. Developer conclusions were not used as acceptance evidence.

## Independent adversarial coverage

The Tester-only suite is `tests/test_p1_011_tester_adversarial.py` and passes 18/18. It covers:

- traversal, Windows and absolute source paths; missing files; malformed UTF-8; duplicate document IDs; invalid status; oversized content; empty/surrogate content; normalization and line-ending cleanup;
- detached repository snapshots, Unicode/NFKC search, bounded query inputs, scope filtering, no-match behavior, deterministic tie-breaking independent of manifest order, and custom-corpus retrieval for both the C01 and C13 wording to disprove fixture mapping;
- the registered `knowledge_search` contract (READ_ONLY, bounded response, typed NOT_FOUND, no `source_file`), the default four-tool surface, and the unchanged `log_search` gap;
- all five routing boundaries with a queued deterministic model harness: stable procedure to `knowledge_search`, user permission state to `permission_query`, work-order state to `work_order_query`, outage state to `incident_query`, and an HTTP 500 log request rejected as the known `log_search` gap with handoff/no evidence/no knowledge substitution.

The harness routing checks demonstrate tool-boundary behavior under scripted model selections; they are not evidence of live model semantic quality. The live key check was performed without reading its value: `DEEPSEEK_API_KEY` was absent, so `LIVE_EVAL_NOT_RUN` is recorded.

## Golden and regression evidence

- `uv run --frozen pytest -q tests/test_knowledge_integration.py tests/test_eval_suite.py` → 14 passed, 1 warning. This includes real registered knowledge runtime coverage for C01/C13, grounded evidence, current-run evidence, and the typed/versioned v0.3 suite.
- The complete backend run includes the existing C03, C05/C12, C10 routing regressions and C09 known-gap coverage. `evals/golden-v0.2.json` is byte-for-byte unchanged from Base (`git diff --quiet ac003587d036b22ff43adee69d93e9f43eb90183 -- evals/golden-v0.2.json`).
- `uv run --frozen pytest -q` → 683 passed, 1 deselected, 1 warning.

## Real FastAPI + Vite browser acceptance

I started a test-only FastAPI server using the real `create_app`, real default knowledge registry/corpus, and a deterministic test-only model provider, then started the Vite dev server and used a fresh Codex in-app browser tab at `http://127.0.0.1:5173/chat`.

The actual UI interaction entered and submitted Golden C01, `故障工单应该怎么关闭？`. The rendered page showed a nonempty grounded reply, `SEARCH`, `knowledge_search`, `knowledge_search: found`, review completion, `REPLY`, and evidence `E1`. Uvicorn recorded:

```text
POST /api/v1/chat HTTP/1.1 200 OK
```

The read-only Run API request `GET /api/v1/runs/e99ff36b-4445-4ff3-9b0f-81dce4ec5107` returned HTTP 200. Its persisted record had distinct identities:

- run ID: `e99ff36b-4445-4ff3-9b0f-81dce4ec5107`
- request ID: `4405fbf8-bfbf-4ff2-9eb6-1c58db74dbc3`
- thread ID: `e8bd49ac-3dc2-4216-b9e6-0bd11a2ade8e`

The Run API record was `SUCCEEDED`, included `SEARCH → knowledge_search → execute_tool → review → REPLY`, and included current-run evidence `E1` with `source=knowledge_search`, `result_status=found`, `document_id=K001`, `reviewed=true`, and the expected SOP title. No local `source_file` or internal path was present in the browser/API result. The real knowledge runtime therefore supplied the provenance; only model selection was deterministic for acceptance.

The requested browser skill file path was checked but was unavailable in this environment. I used the installed browser runtime/API documentation and performed the acceptance through the real in-app browser UI; this was not replaced by an HTTP-only check.

## Validation evidence

```text
uv run --frozen pytest -q tests/test_p1_011_tester_adversarial.py
→ 18 passed

uv run --frozen pytest -q
→ 683 passed, 1 deselected, 1 warning

uv run --frozen ruff check .
→ All checks passed

uv run --frozen mypy src
→ Success: no issues found in 62 source files

uv lock --check
→ Resolved 55 packages; PASS

git diff --check
→ PASS

cd web && npm test -- --run
→ 4 files passed; 41 tests passed

cd web && npm run lint
→ PASS

cd web && npm run build
→ PASS
```

## Tester changes

Tester Evidence HEAD `bfe73a3d25aba8873773542147fc798cb0ea2c74` contains only:

- `tests/test_p1_011_tester_adversarial.py`
- `tests/p1_011_browser_server.py`

No product implementation, frontend product file, task specification, or ADR was modified.
