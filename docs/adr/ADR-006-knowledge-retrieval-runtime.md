# ADR-006 — Knowledge retrieval runtime

## Status

Accepted.

TASK-P1-011 passed the PM Architecture Gate.

## Context

The Agent needs a bounded capability for stable internal operating guidance.
The existing kernel already provides model-selected typed tools, result review,
current-run Evidence, grounded response planning, run observability, and
application-level conversation continuity. Knowledge retrieval must fit those
boundaries without adding a second graph, an opaque corpus prompt, or a new
external service. The first release is synthetic and local so tests and demos
remain deterministic and require no credentials or network access.

## Decision

Add `knowledge_search` as a registered `READ_ONLY` tool backed by a versioned
local corpus and a provider-neutral repository/search boundary:

```text
manifest + Markdown
  → LocalKnowledgeRepository
    → LexicalKnowledgeSearchService
      → knowledge_search / ToolRegistry
        → review_tool_result
          → current-run Evidence
            → grounded response plan and renderer
```

The graph topology, canonical `OpsAgentState`, conversation service, and
grounding contract remain unchanged. The model still decides whether to
search and selects the registered tool; Python only validates the declared
tool call, applies the read-only policy, executes it, and routes on the
validated control action.

## Why a registered tool

Knowledge is an evidence-producing capability, like the existing permission,
work-order, and incident queries. Registering it lets the existing selection,
argument validation, timeout, duplicate-call, review, trace, Evidence, and
grounding boundaries apply uniformly. A separate graph would duplicate loop
policy and create a second route for evidence and persistence. The tool does
not inspect intent strings, case IDs, or query fixtures.

## Corpus and repository

The repository-owned corpus is under `src/opsmind/knowledge/data/` and is
described by `manifest.json` with schema version, corpus identity/version,
document identity, title, system, type, document version, update date, status,
relative source file, and tags. The synthetic corpus contains four distinct
SOP documents (`K001`–`K004`) covering work-order closure, equipment-ledger
export, access requests, and QualityHub report export. Only `ACTIVE` documents
are indexed; `RETIRED` documents are accepted as metadata but excluded from
search.

`KnowledgeRepository` exposes validated active documents, document lookup, and
deterministic chunks. `LocalKnowledgeRepository` is the current implementation
and can be replaced without changing the tool contract or Agent nodes. It
resolves source files beneath the configured corpus root, rejects traversal,
absolute/drive-qualified and symlink escapes, bounds file sizes, validates UTF-8
and metadata, and emits a generic `KNOWLEDGE_CORPUS_INVALID` error without
paths or source content.

## Cleaning and chunking

Cleaning applies Unicode NFKC normalization, normalizes CRLF/CR to LF, removes
trailing spaces per line, collapses runs of three or more blank lines, trims
outer whitespace, and rejects empty, overlarge, control-character, or surrogate
content. Chunking uses a fixed 1,000-character window and a 200-character
overlap. Chunk identity is deterministic from document ID, version, and start
offset; the section is the nearest preceding Markdown heading or document
title. The corpus is loaded once into a repository and returned through deep
copies, so callers cannot mutate another run's index.

## Retrieval algorithm

`LexicalKnowledgeSearchService` is independent of storage and Agent policy. It
normalizes query/document text with NFKC and case folding, tokenizes ASCII
identifiers/words, and creates bigrams for Chinese runs. It computes a bounded
BM25-style lexical score over title, section, and chunk content. A result must
have lexical support; ties are resolved by descending score and then
`document_id`, `chunk_id`. An exact optional `system_id` filter is applied
before scoring. Empty, oversized, or unsupported direct-service inputs fail
closed as no match. No query text is mapped directly to a fixture response.

Embeddings, a vector database, a semantic RAG framework, and external
embedding/knowledge connectors are deferred. A future backend may implement the
same `KnowledgeRepository`/search service boundary, but it must preserve the
typed tool request and response contract and pass a new architecture gate.

## Tool contract and provenance

`KnowledgeSearchRequest` contains a bounded nonblank `query` (maximum 512
characters) and an optional exact `system_id` (maximum 128 characters).
`KnowledgeSearchResponse` contains `FOUND` or `NOT_FOUND`; a found result must
carry the document ID, chunk ID, title, section, excerpt, system, document
type, version, and ISO update date. A not-found result cannot carry provenance
or an excerpt. The response is deliberately one best chunk, keeping model
review and Evidence bounded and preventing the full document from entering
context.

Manifest `source_file` is an ingestion detail. It is never part of the tool
response, Evidence, API response, run record, conversation checkpoint, or
error message. User-visible provenance is the stable document/chunk identity,
title, section, system, version, and update date. Source content remains
untrusted data and is rendered only through the existing typed field
presentation and escaping boundary.

## Trust boundary and conversation behavior

The raw adapter result exists only between `execute_tool` and
`review_tool_result`. Review receives the selected typed result schema and
compact result payload. The generic reviewer projects a source-qualified
Evidence item whose `key_fields` are validated against the registered response
schema. Grounded plans can reference only that current-run Evidence by stable
ID and canonical field path; the deterministic renderer supplies values and
limitation wording.

Conversation restoration carries bounded task/fact/entity/checkpoint context,
not raw tool output or historical Evidence. A follow-up turn therefore must
execute `knowledge_search` again to obtain current-run Evidence. This keeps a
prior assistant sentence from silently becoming a fact source while retaining
the thread's task and relevant scalar entities.

## Scope and not-found policy

`system_id`, when supplied, is an exact repository scope. A missing or retired
document, an unknown scope, and a query with no lexical support all return the
typed `NOT_FOUND` result. The Agent may decide to clarify, answer with a
bounded limitation, or choose another registered capability; the Python
harness does not route those outcomes from business wording. `knowledge_search`
does not answer current permissions, work-order status, incidents, or logs;
`log_search` remains intentionally unregistered.

## Evaluation and observability

Chat and Eval call the same `AgentExecutionService`, runtime registry,
repository, search service, review node, and grounding path. Golden Suite
v0.3 adds real knowledge cases C01 and C13 while preserving permission routing
(C03), work-order behavior (C05/C12), incident behavior (C10), and the
`LOG_SEARCH_NOT_IMPLEMENTED` known gap (C09). The existing generic evaluator
registry includes action occurrence so knowledge search can be asserted without
answer-text matching.

Knowledge execution appears naturally in the safe trace, tool-call metadata,
current-run Evidence, and persisted AgentRun projections. Persistence does
not include the corpus, unselected chunks, search internals, source paths,
prompts, model payloads, or raw tool results. There is no Knowledge Admin API,
upload/edit/delete flow, chunk viewer, or retrieval-tuning UI in this ADR.

## Consequences and limitations

The release provides a reproducible local baseline with explicit provenance,
bounded context, stable ranking, system scope, and a replaceable storage/search
boundary. Lexical matching will miss semantic paraphrases and does not provide
document ACLs beyond the current system filter; those are known scope limits.
The corpus is synthetic, local, and loaded at runtime construction. DeepSeek
live evaluation remains opt-in and is reported separately from deterministic
mock/integration validation.

## Accepted limitations

- Retrieval is lexical only.
- The corpus is synthetic and local.
- Retrieval returns one primary chunk.
- No semantic reranker or vector database is included.
- No external enterprise connector is included.
- No knowledge administration API or UI is included.
- No enterprise document ACL is provided.
- DeepSeek live quality was not executed (`LIVE_EVAL_NOT_RUN`).
- The explicit-offset ISO `updated_at` validation limitation is retained as
  technical debt; shipped corpus metadata uses date-only values.
