# TASK-P1-011 Developer Report

## Decision

`IMPLEMENTATION COMPLETE — READY FOR INDEPENDENT TEST`

## Identity

- Base SHA: `ac003587d036b22ff43adee69d93e9f43eb90183`
- Product HEAD: `aa278f024cd6e0aa6b5720db732325d3cdf7b153`
- Issue: `#26`
- Draft PR: `#27`
- Branch: `task/TASK-P1-011-dev`
- Execution override: Luna Max for non-Reviewer agents; Astra Low for the
  Reviewer, as recorded at the top of the task artifact.

## Files changed

- Added the provider-neutral `src/opsmind/knowledge/` domain with bounded
  metadata, corpus validation, deterministic cleaning/chunking, the
  `KnowledgeRepository` boundary, local implementation, lexical search, and
  typed `knowledge_search` registration.
- Added four repository-owned synthetic SOP documents (`K001`–`K004`) and
  manifest version `1.0.0`; only ACTIVE documents are indexed.
- Registered `knowledge_search` in the existing four-tool READ_ONLY registry
  and exported its typed request/response contracts.
- Added Golden Suite `0.3` with C01 upgraded and C13 added; retained
  `evals/golden-v0.2.json` byte-for-byte unchanged.
- Added generic `action_occurred` evaluation support and knowledge unit,
  integration, API, conversation, context, provenance, and leakage coverage.
- Updated `README.md`, `docs/ARCHITECTURE.md`, `docs/AGENT_KERNEL.md`,
  `docs/API.md`, the full `docs/adr/ADR-006-knowledge-retrieval-runtime.md`,
  and the active task artifact.

## Architecture summary

The runtime is:

```text
versioned manifest + Markdown
  → LocalKnowledgeRepository
    → LexicalKnowledgeSearchService
      → knowledge_search / ToolRegistry
        → review_tool_result
          → current-run Evidence
            → grounded response plan and renderer
```

No LangGraph topology, grounding semantics, conversation schema, or public
Knowledge Admin API changed. The model continues to decide SEARCH and select a
registered tool; Python validates and executes that declared call. Retrieval
contains no case, query, or business-phrase routing table.

## Corpus and retrieval

- `K001`: EquipFlow fault work-order closure SOP.
- `K002`: EquipFlow equipment-ledger export SOP.
- `K003`: EquipFlow access-request procedure.
- `K004`: QualityHub inspection-report export SOP.
- Cleaning uses Unicode NFKC, normalized line endings, trailing-space removal,
  bounded blank-line normalization, and fail-closed content validation.
- Chunking is deterministic 1,000-character windows with 200-character overlap
  and stable `document_id.version.offset` chunk IDs.
- Lexical retrieval supports ASCII identifiers/English tokens and Chinese
  bigrams, uses a BM25-style score, applies exact optional `system_id` scope,
  and breaks ties by document and chunk identity.
- The tool returns one best bounded chunk or typed `not_found`; provenance is
  document ID, chunk ID, title, section, system, document type, version, and
  update date. Manifest source paths, unselected content, and index internals
  stay behind the repository boundary.

## Agent, conversation, and evaluation behavior

The knowledge result follows the existing generic ToolRegistry → review →
current-run Evidence → grounded renderer path. Conversation acceptance uses a
shared thread with distinct request/run IDs; the second continuation executes a
fresh knowledge search and receives fresh E1 Evidence rather than promoting
historical Evidence.

The official Golden Suite C01 and C13 cases were run through the real
`AgentExecutionService` and real registered knowledge runtime with a queued
test provider; both returned `PASS` with the expected documents, action, tool,
result status, evidence source, and nonempty reply. Existing full regression
coverage preserves permission routing for C03, work-order behavior for C05/C12,
incident behavior for C10, and the C09 `LOG_SEARCH_NOT_IMPLEMENTED` gap.

## Validation

- Backend: `uv run --frozen pytest -q` — **665 passed, 1 deselected, 1
  existing Starlette deprecation warning**.
- Focused knowledge/API/conversation/eval tests — **35 passed**.
- Ruff: `uv run --frozen ruff check .` — **PASS**.
- Mypy: `uv run --frozen mypy src` — **PASS**, 62 source files.
- Lock: `uv lock --check` — **PASS**, 55 packages resolved.
- Diff: `git diff --check` — **PASS**.
- Frontend: `npm test -- --run` — **41 passed in 4 files**; `npm run lint` —
  **PASS**; `npm run build` — **PASS**.
- Browser: **PASS** with real FastAPI, real Vite, the in-app browser, a
  temporary SQLite store, and a test-only queued provider. Vite root and
  `/api/v1/health` returned HTTP 200. The UI submitted
  `故障工单应该怎么关闭？` and rendered a nonempty reply with
  `knowledge_search: found` and the `execute_tool` trace. The observed run was
  `run_id=d0ab6e4d-8761-46bd-b130-494066cdc377`,
  `thread_id=5906ca37-b839-496f-af51-f9a0c0d4334e`, and
  `request_id=6173a2ed-6443-4cab-adde-a638958ede77`; evidence source was
  `knowledge_search`, document `K001`. DOM/API inspection found no
  `source_file` or internal corpus path leakage.
- Live DeepSeek: `LIVE_EVAL_NOT_RUN`; `DEEPSEEK_API_KEY` presence was false.
  No key value or other secret was read or printed.

## Known limitations

- Retrieval is lexical and may miss semantic paraphrases.
- The corpus is synthetic, local, artifact-versioned, and loaded at runtime
  construction; there is no runtime update path.
- Only one primary chunk is returned, with no reranker, embeddings, vector
  backend, semantic synthesis, or enterprise document ACL platform.
- System scope is an exact filter, not multi-tenant authorization.
- DeepSeek live quality remains unmeasured in this environment.

## Explicit scope exclusions

No `log_search`, log ingestion, embeddings, vector DB, semantic reranker,
external knowledge connector, web search, document upload/editor/admin API,
knowledge ACL platform, crawler, automatic update scheduler, LLM query rewrite
or summarizer, long-term memory, write tool, human approval workflow,
LangGraph checkpoint/resume, or unrelated UI was added.

Developer does not declare the task finally approved. Independent Tester,
Reviewer, CI, PM Architecture Gate, and the existing Draft/unmerged PR policy
remain required. Merge remains prohibited.
