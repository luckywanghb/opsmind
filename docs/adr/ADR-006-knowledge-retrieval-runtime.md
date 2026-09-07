# ADR-006 — Knowledge retrieval runtime

Status: Proposed for TASK-P1-011. PM Architecture Gate pending.

## Planned decision

Implement a registered READ_ONLY knowledge_search tool backed by a versioned
local synthetic corpus, deterministic cleaning and fixed-size overlapping chunks,
a backend-neutral KnowledgeRepository, and an independent lexical search service.
Return one bounded best chunk with stable provenance through the existing typed
ToolRegistry → review_tool_result → current-run Evidence → grounded plan →
deterministic renderer boundary. Preserve graph topology and conversation semantics.

No embeddings, vector database, external connector, knowledge administration API,
new production dependency, or log search is included. Implementation details and
validation will be completed in the Developer phase. Merge is prohibited pending PM.
