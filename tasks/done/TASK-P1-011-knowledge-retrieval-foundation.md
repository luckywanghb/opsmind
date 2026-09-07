# TASK-P1-011 — Knowledge / SOP Retrieval Foundation

> Final OpsMind Agent Model Governance is set by PM / User authority and is
> recorded in `AGENTS.md`. Sub-agents cannot override it or create a new PM
> override. There is no silent model fallback; required != actual makes a gate
> invalid.

## Status

`DONE`

- PM Architecture Gate: `APPROVED`
- Architecture: `ACCEPTED`
- Merge: `AUTHORIZED`
- Task state: `DONE`
- Base: `ac003587d036b22ff43adee69d93e9f43eb90183`
- Product SHA: `aa278f024cd6e0aa6b5720db732325d3cdf7b153`
- Tester Evidence HEAD: `bfe73a3d25aba8873773542147fc798cb0ea2c74`
- Reviewed HEAD: `ef286678d4ddda3def196ccbf07b6e7c321a9300`
- Pre-finalization Delivery HEAD: `2bdaba3748d8f28816391f80792b926c809fbe8f`
- Independent Tester: Luna Max / Max — `PASS`, `B0/M0/m0/N0`
- Reviewer: Astra Low / Low — `APPROVE`, `B0/M0/m1/N0`

## 0. Task Identity

Repository:

`luckywanghb/opsmind`

Required Base:

`ac003587d036b22ff43adee69d93e9f43eb90183`

Phase:

`Phase 3 — Context, Knowledge & Investigation`

Task Type:

`HIGH RISK / ARCHITECTURE IMPACT`

PM Architecture Gate:

`APPROVED`

Architecture:

`ACCEPTED`

Merge:

`AUTHORIZED`

Suggested branch:

`task/TASK-P1-011-dev`

Suggested task artifact:

`tasks/active/TASK-P1-011-knowledge-retrieval-foundation.md`

Required ADR:

`docs/adr/ADR-006-knowledge-retrieval-runtime.md`

---

# 1. Governance Baseline

TASK-P1-011 uses the FINAL OpsMind Agent Model Governance recorded in
`AGENTS.md`. The authoritative mapping is:

```text
PM / Architect       Astra Medium / Medium / user controlled
Developer            Luna Max / Max
Independent Tester   Luna Max / Max
Reviewer             Astra Low / Low
Delivery Reporter    Luna Max / Max
Escalation Architect Astra Medium / Medium / conditional
```

This mapping comes from PM / User authority. No silent fallback and no
sub-agent PM override are permitted. Historical reports remain historical
evidence and are not rewritten.

---

# 2. Background

OpsMind 当前已经具备：

```text
P1-006
Safe Read-only Agent Kernel
+ Evidence-Bound Grounded Response

P1-007
Run Persistence & Observability

P1-008
Eval Runtime & Golden Suite

P1-009
Real Eval UI

P1-010
Conversation Persistence & Context Continuity
```

当前 Agent 已经能够：

```text
User Query
  ↓
Understand
  ↓
Decide
  ↓
Select Tool
  ↓
Execute Tool
  ↓
Review Tool Result
  ↓
Canonical Evidence
  ↓
Grounded Response Plan
  ↓
Deterministic Grounded Renderer
```

但目前只有：

* `work_order_query`
* `permission_query`
* `incident_query`

三个业务数据型 READ_ONLY Tool。

Golden Case C01：

```text
故障工单应该怎么关闭？
```

当前明确存在：

```text
KNOWN GAP:
KNOWLEDGE_RUNTIME_NOT_IMPLEMENTED
```

并已经期望：

```text
Action = SEARCH
Tool = knowledge_search
```

TASK-P1-011 的目标就是正式关闭这个 gap。

---

# 3. Product Goal

实现一个真正可以被 Agent 调用的：

`knowledge_search`

使 Agent 可以针对以下类型的问题检索内部 SOP / 操作手册 / FAQ：

* “故障工单应该怎么关闭？”
* “设备台账怎么导出？”
* “管理员权限应该怎么申请？”
* “某个系统功能应该怎么操作？”
* “这个业务流程是什么？”

最终形成：

```text
User Question
    ↓
Model decides SEARCH
    ↓
Model selects knowledge_search
    ↓
Knowledge Retrieval Runtime
    ↓
Relevant bounded SOP chunk
    ↓
Tool Result Review
    ↓
Canonical current-run Evidence
    ↓
Grounded Response
```

重点：

**知识库内容必须通过现有 Tool → Evidence → Grounding 链路进入回答。**

禁止绕过 P1-006。

---

# 4. Core Architecture Decision

P1-011 第一版本：

**不要建设通用“大 RAG 平台”。**

采用：

```text
Versioned Synthetic Knowledge Corpus
        ↓
Deterministic Cleaning
        ↓
Deterministic Chunking
        ↓
KnowledgeRepository
        ↓
LexicalKnowledgeSearchService
        ↓
knowledge_search
        ↓
Existing ToolRegistry
        ↓
Existing Evidence Pipeline
```

本版本明确：

```text
NO embedding API
NO vector database
NO reranker model
NO external document connector
NO document upload
NO LLM query rewriting
```

第一目标不是追求最高 Recall。

第一目标是建立：

**正确、可控、可评测、可升级的 Knowledge Retrieval architecture boundary。**

---

# 5. Why Lexical Retrieval First

本阶段建议实现一个 provider-free 的 deterministic lexical retriever。

必须支持：

* 中文
* 英文/数字/identifier
* Unicode normalization
* deterministic ranking
* system scope filtering
* stable tie breaking

推荐实现：

```text
Unicode normalization
+
Latin/alphanumeric tokens
+
Chinese character bigram/token strategy
+
BM25-style lexical ranking
```

允许 Developer 在保持上述性质的情况下使用等价 deterministic lexical algorithm。

但禁止：

```text
if query == "故障工单应该怎么关闭？":
    return K001
```

禁止：

* query substring routing table
* case-id routing
* C01-specific branch
* fixture phrase mapping
* business-question hardcode

---

# 6. Knowledge Domain

建议新增：

```text
src/opsmind/knowledge/
    __init__.py
    models.py
    repository.py
    corpus.py
    retrieval.py
    data/
```

实际文件拆分可以合理调整，但必须保持领域边界。

---

# 7. KnowledgeRepository

建立 backend-neutral：

`KnowledgeRepository`

职责：

* 提供有效 Knowledge Document
* 提供 deterministic chunks
* 不负责 Agent routing
* 不负责模型调用
* 不负责最终回答

Repository 不得依赖 LangGraph。

推荐接口语义：

```text
list_active_documents()
get_document(document_id)
list_chunks(...)
```

Search / ranking 应由独立：

`KnowledgeSearchService`

负责。

不要把 repository、ranking、Agent tool 全塞进一个类。

---

# 8. Versioned Knowledge Corpus

创建一个版本化 synthetic internal knowledge corpus。

建议：

```text
src/opsmind/knowledge/data/manifest.json
src/opsmind/knowledge/data/*.md
```

Corpus 必须是 repository-owned、deterministic、无外部网络依赖的数据。

Manifest 至少包含：

```text
schema_version
corpus_id
corpus_version

document:
  document_id
  title
  system_id
  document_type
  version
  updated_at
  status
  source_file
  tags
```

Document status 至少支持：

```text
ACTIVE
RETIRED
```

只有 ACTIVE 文档允许被检索。

---

# 9. Minimum Synthetic Corpus

至少准备 4 份相互有区分度的知识文档。

## K001 — EquipFlow 故障工单关闭 SOP

必须能够回答：

```text
故障工单应该怎么关闭？
```

内容至少覆盖：

* 关闭前需要确认什么
* 关闭操作的主要步骤
* 哪些信息需要填写
* 未完成处理时不能直接关闭等合理 synthetic rule

不要照搬 Golden Case 文本。

---

## K002 — EquipFlow 设备台账导出 SOP

能够回答例如：

```text
设备台账怎么导出？
```

用于证明：

`knowledge_search` 不是为 C01 单独实现。

---

## K003 — EquipFlow 权限申请流程

能够回答：

```text
我要怎么申请设备台账权限？
```

这个文档非常重要，因为它用于测试 Tool Routing 边界：

```text
“怎么申请权限？”
→ knowledge_search

“为什么我现在没有权限？”
→ permission_query
```

不能因为知识库里存在权限文档，就导致 C03 从 `permission_query` 漂移到 `knowledge_search`。

---

## K004 — 另一个系统的 SOP

例如：

```text
QualityHub
```

或者项目现有 synthetic manufacturing domain 中合理的另一个系统。

目的：

测试：

* cross-system ranking
* system scope
* generic retrieval

不要让整个知识库只有 EquipFlow。

---

# 10. Cleaning Strategy

实现 deterministic knowledge cleaning。

本任务不需要复杂 NLP cleaning。

至少执行：

* normalize line endings
* Unicode normalization
* remove invalid empty content
* remove unnecessary trailing whitespace
* normalize excessive blank lines
* validate metadata
* reject malformed source documents

不得进行可能改变业务语义的“大模型清洗”。

不要自动删除：

* warning
* limitation
* prerequisite
* exception
* 注意事项

这些通常是 SOP 的关键知识。

---

# 11. Chunking Strategy

采用简单、可靠的：

**fixed-size + overlap**

而不是语义切片模型。

推荐约束：

```text
target chunk:
约 800–1200 chars

overlap:
约 150–250 chars

absolute max prompt-visible excerpt:
<= 2000 chars
```

可以优先在：

* heading
* paragraph
* list boundary

附近断开，但结果必须 deterministic。

Chunk 必须拥有稳定身份：

```text
document_id
chunk_id
section
```

同一个 corpus version 重载后：

`chunk_id` 必须稳定。

禁止 random UUID chunk id。

---

# 12. Knowledge Model

建议建立类似：

```text
KnowledgeDocument
KnowledgeChunk
KnowledgeSearchMatch
```

其中 KnowledgeChunk 至少包含：

```text
document_id
chunk_id
title
section
system_id
document_type
version
updated_at
content
```

所有 prompt-visible string 必须有明确长度上限。

---

# 13. Search Scope

Search Service 推荐接口：

```text
search(
    query,
    system_id=None
)
```

Tool 第一版本只需要返回：

**最佳匹配的一个 bounded chunk。**

不要为了“看起来更像 RAG”一次塞 5～10 个 chunk 给 Agent。

理由：

* 当前 Evidence contract 是 compact
* 模型 attention 有限
* 当前问题通常只需要一个 SOP 段落
* 可以控制 latency/context
* 以后可以在不改 Tool boundary 的情况下增加 retrieval sophistication

内部 search service 可以计算多个候选再选 best hit。

但 Agent-visible Tool Result 第一版保持小。

---

# 14. knowledge_search Tool Contract

新增：

`KnowledgeSearchRequest`

建议：

```text
query: str
system_id: str | None
```

Query 必须：

* non-empty
* bounded
* schema validated

不建议第一版让模型传：

* threshold
* ranking algorithm
* chunk size
* embedding model
* index name

这些是 implementation detail，不是 Agent 应该决定的参数。

---

# 15. KnowledgeSearchResponse

建议：

```text
result_status

document_id
chunk_id
title
section
excerpt

system_id
document_type
version
updated_at
```

FOUND 时：

以上 provenance + excerpt 必须完整。

NOT_FOUND 时：

不得伪造 document metadata。

必须使用 typed model validator 保证状态一致性。

---

# 16. Provenance Is Mandatory

知识搜索不是：

```text
query → answer
```

而应该是：

```text
query
→ document
→ chunk
→ source excerpt
```

最终 Evidence 必须能够明确知道：

* 来自哪个 Document
* 哪个 Chunk
* 哪个 Section
* 哪个 Version
* 文档更新时间

这样后续才能实现：

* citation
* knowledge update
* bad case diagnosis
* stale knowledge analysis
* document management UI

---

# 17. Tool Description

`knowledge_search` 的 ToolSpec 描述必须明确告诉模型：

适合：

```text
稳定的内部知识：
SOP
操作步骤
业务说明
FAQ
帮助文档
制度/流程说明
```

不适合：

```text
用户当前权限
实时工单状态
当前 Incident
实时日志
当前系统状态
```

例如语义应接近：

```text
搜索内部版本化 SOP、操作手册和 FAQ，用于回答稳定的操作方式、
流程说明和业务知识。不得用于查询实时工单状态、当前用户权限、
实时事件或日志。
```

Tool signature 的设计本身是本任务的重要验收内容。

---

# 18. Register Into Existing ToolRegistry

默认 Registry 最终至少包含：

```text
work_order_query
permission_query
incident_query
knowledge_search
```

`knowledge_search`：

```text
mode = READ_ONLY
```

必须沿用：

`RegisteredTool + ToolSpec + typed Request/Response`

禁止创建第二套 Tool Runtime。

---

# 19. Graph Constraint

原则上：

**不得修改 LangGraph topology。**

现有：

```text
decide_action
→ select_tool
→ execute_tool
→ review_tool_result
→ decide_action
```

已经足以运行 knowledge search。

不要新增：

```text
knowledge_node
rag_node
retrieval_graph
knowledge_router_node
```

如果 Developer 判断“不修改 Graph 无法完成”：

`STOP → PM Architecture Gate`

不能自行扩图。

---

# 20. Evidence Boundary

这是 P1-011 最重要的架构约束之一。

Knowledge Search Result：

必须进入：

```text
review_tool_result
    ↓
EvidenceItem
    ↓
GroundedResponsePlan
    ↓
Grounded Renderer
```

禁止：

```text
knowledge_search result
→ 直接让 LLM 生成用户答案
```

禁止：

```text
retrieved chunk
→ response.message
```

禁止 bypass：

* Evidence ID validation
* Tool response schema validation
* Grounded Response Plan
* deterministic renderer

---

# 21. Generic Evidence Requirement

原则上不得在：

```text
review_tool_result.py
grounding.py
graph.py
```

中加入：

```text
if tool_name == "knowledge_search":
```

这类业务特判。

Knowledge Tool 应通过：

* typed schema
* registry
* field presentation
* existing generic evidence pipeline

自然工作。

如果必须增加通用能力，应保证：

**任何未来 custom read-only tool 同样受益。**

不能只修 `knowledge_search`。

---

# 22. Context Engineering Requirement

知识库完整文档不得进入 Agent Context。

只允许：

```text
query-relevant bounded chunk
```

进入 tool result review。

必须证明：

```text
Full Document
    ≠
Prompt Context
```

目标是：

**检索所需信息，而不是把整个知识库塞给模型。**

---

# 23. No Historical Evidence Promotion

P1-010 边界继续有效。

Knowledge evidence：

只能属于：

`current Run`

Conversation checkpoint 可以保留安全的 conversation facts / entities。

但：

**上一轮 Knowledge Evidence 不得在下一轮自动变成 current-run Evidence。**

如果第二轮用户继续问 SOP 的事实：

Agent 应当能够重新执行 `knowledge_search` 获取本轮 Evidence。

---

# 24. Retrieval NOT_FOUND

当 query 没有可靠匹配：

必须返回 typed：

```text
NOT_FOUND
```

不得返回：

* 最接近但明显不相关的文档
* 模型生成答案
* fake fallback result

Agent 后续可以：

* ASK_USER
* REPLY with limitation
* choose another registered capability
* TRANSFER_HUMAN

由现有 Agent loop 决定。

Search engine 本身不得决定 Agent action。

---

# 25. System Scope

当：

`system_id`

明确提供时：

必须先限制合法 document scope，再 ranking。

例如：

```text
system_id = EquipFlow
```

不能因为词面相似而返回 QualityHub 文档。

如果 system_id 未提供：

允许全 corpus 检索。

---

# 26. Corpus Safety

Manifest/source loader 必须验证：

* duplicate document_id
* duplicate chunk_id
* invalid schema_version
* invalid status
* missing source
* empty document
* oversized metadata
* unsafe relative path / `..`
* malformed UTF-8 / invalid content where applicable

不得把本地绝对路径暴露到 Tool Result、Evidence 或 API。

---

# 27. P1-006 Grounding Regression

必须特别验证：

Knowledge excerpt：

是 source data。

不是 model prose。

最终回答中的知识事实必须来自：

`KnowledgeSearchResponse`

中的实际字段。

不得因为知识属于“文档”，就放宽 grounding rule。

---

# 28. Golden Suite v0.3

保持：

`golden-v0.2.json`

完全不变。

新增：

`evals/golden-v0.3.json`

---

# 29. C01 Upgrade

C01：

```text
故障工单应该怎么关闭？
```

在 v0.3 中删除：

```text
KNOWLEDGE_RUNTIME_NOT_IMPLEMENTED
```

C01 必须正式 PASS。

至少验证：

```text
intent = SYSTEM_OPERATION
request_type = HOW_TO
SEARCH occurred
knowledge_search used
result FOUND
correct SOP document returned
grounded evidence exists
final reply nonempty
```

---

# 30. Add One New Knowledge Golden Case

建议新增：

`C13`

例如：

```text
设备台账怎么导出？
```

期望：

```text
HOW_TO
SEARCH
knowledge_search
K002-related evidence
grounded reply
```

目的：

证明：

P1-011 不是针对 C01 的 hardcode。

---

# 31. Preserve Existing Routing

以下行为不得退化。

### Existing C03

```text
别人都有设备台账菜单，为什么我没有？
```

必须继续：

`permission_query`

不能错误切换为 knowledge_search。

---

### Existing C05 / C12

必须继续：

`work_order_query`

---

### Existing C10

必须继续：

`incident_query`

---

### Existing C09

仍保持：

```text
LOG_SEARCH_NOT_IMPLEMENTED
```

TASK-P1-011 禁止顺手实现 `log_search`。

---

# 32. Adversarial Tool-Routing Tests

Independent Tester 必须至少攻击：

### Stable procedure

```text
设备台账权限怎么申请？
```

Expected:

`knowledge_search`

### User-specific state

```text
为什么 U10023 没有设备台账权限？
```

Expected:

`permission_query`

### Current work-order state

```text
WO20260001现在到谁了？
```

Expected:

`work_order_query`

### Site-wide outage

```text
星川基地的人都进不去 EquipFlow
```

Expected:

`incident_query`

### Log diagnosis

```text
EquipFlow HTTP 500
```

不得假装 knowledge_search 可以替代 log_search。

---

# 33. Knowledge Retrieval Tests

至少测试：

* Chinese query retrieval
* English / identifier retrieval
* punctuation differences
* case normalization
* Unicode normalization
* same input → same rank
* ranking tie determinism
* system filter
* retired document exclusion
* no-match behavior
* malformed corpus
* duplicate IDs
* chunk stability
* chunk size
* overlap behavior

---

# 34. No Query Hardcoding Test

Tester 必须源码扫描及行为验证：

不得出现针对：

```text
C01
C13
故障工单应该怎么关闭
设备台账怎么导出
```

的 semantic branch。

Corpus 内容包含这些业务概念是正常的。

但代码不能通过：

`query text → fixture response`

直接映射。

---

# 35. Context Leakage Test

设计一个超过单 chunk 大小的 test document。

在相关 chunk 外放入：

```text
UNSELECTED_DOCUMENT_TAIL_SENTINEL
```

执行只匹配前段内容的 search。

必须证明 sentinel 不进入：

* Tool Result
* Evidence
* Model review context
* Run canonical Evidence
* final reply

以证明：

**只有检索到的 bounded chunk 进入上下文。**

---

# 36. Provenance Leakage Test

内部 source path，例如测试 sentinel：

```text
/private/internal/knowledge/source.md
```

不得出现在：

* Chat response
* Evidence
* Run public API
* conversation checkpoint
* error response

用户侧只能看到 stable provenance：

```text
document_id
chunk_id
title
section
version
updated_at
```

---

# 37. Browser Acceptance

必须使用：

```text
Real FastAPI
+
Real Vite frontend
+
deterministic mock model provider
+
real knowledge_search runtime
```

执行至少一个完整浏览器流程：

```text
User:
故障工单应该怎么关闭？

Agent:
Understand
→ SEARCH
→ knowledge_search
→ Evidence
→ Grounded Reply
```

验证：

* HTTP 200
* final reply nonempty
* knowledge_search 真正执行
* Run 有新的 run_id
* Evidence source = knowledge_search
* source document provenance 可追踪
* 没有 hardcoded browser response

---

# 38. Conversation + Knowledge Acceptance

增加跨 Run 场景，例如：

Turn 1：

```text
故障工单应该怎么关闭？
```

Turn 2：

```text
那关闭前需要确认什么？
```

要求：

* same thread_id
* different request_id
* different run_id
* second turn recognized as continuation where appropriate
* relevant entity/task context retained
* second turn重新执行 knowledge_search
* second turn使用新的 current-run Evidence
* 不以第一轮 assistant 文本作为事实证据

---

# 39. Eval Runtime

Golden v0.3 必须继续走：

`AgentExecutionService`

禁止：

* eval-specific knowledge injection
* manually concatenated knowledge
* special fake `knowledge_search`
* evaluator bypass

Chat 与 Eval 必须使用同一个真实 Knowledge Runtime。

---

# 40. Run Observability

知识搜索执行必须自然出现在现有：

* trace
* tool_calls
* Evidence
* AgentRun

中。

但不得持久化：

* full knowledge corpus
* unselected chunks
* internal source file path
* search index internals

---

# 41. Public API

P1-011 原则上：

**不新增 Knowledge Admin API。**

本任务的产品入口：

* Chat
* Eval
* Run observability

已经足够验证 capability。

以下推迟：

```text
GET /knowledge/*
POST /knowledge/*
upload document
edit document
delete document
```

如果 Developer 认为必须新增 Knowledge API：

先 STOP，交 PM 判断。

---

# 42. Frontend Scope

本任务不建设：

* 知识库管理页面
* 文档上传页
* chunk viewer
* document editor
* retrieval tuning UI

现有 Chat / Eval UI 只做兼容性调整。

若 Golden Suite version / result metadata 是动态读取：

不要硬编码 UI v0.3。

---

# 43. Dependencies

优先：

**不新增生产 dependency。**

当前 Python 标准库足以实现 deterministic lexical retrieval。

禁止本任务直接引入：

* Chroma
* Pinecone
* Milvus
* Elasticsearch
* FAISS
* sentence-transformers
* LangChain RAG stack
* external embedding SDK

如 Developer 认为新的第三方 retrieval dependency 是不可避免的：

`STOP → PM Architecture Gate`

---

# 44. ADR-006 Required Decisions

ADR-006 至少说明：

1. 为什么 Knowledge Retrieval 是 registered Tool，而不是独立 Graph。
2. 为什么第一版采用 versioned local corpus。
3. 为什么使用 deterministic lexical retrieval。
4. 为什么暂不使用 embedding / vector DB。
5. Cleaning strategy。
6. Chunking strategy。
7. Provenance contract。
8. Knowledge Tool Request / Response boundary。
9. 为什么只返回 bounded best chunk。
10. Knowledge → Evidence → Grounding 的 trust boundary。
11. 为什么历史知识不能自动升级为下一 Run Evidence。
12. system scope 行为。
13. NOT_FOUND policy。
14. 后续如何替换为 embedding/vector backend 而不改变 Agent tool contract。
15. 当前限制和 future evolution。

ADR Status：

```text
Accepted.
TASK-P1-011 passed the PM Architecture Gate.
```

---

# 45. Documentation

至少更新：

* `docs/ARCHITECTURE.md`
* `docs/AGENT_KERNEL.md`
* `docs/API.md`（若行为说明需要）
* README 中当前 capability / limitation，如确有对应章节

文档必须继续明确：

P1-011 有：

```text
Knowledge Retrieval
```

但没有：

```text
general semantic RAG platform
external enterprise KB connector
knowledge admin UI
log search
```

---

# 46. Developer Validation

Developer 完成后至少运行：

```bash
uv run --frozen pytest
uv run --frozen ruff check .
uv run --frozen mypy src
uv lock --check
git diff --check
```

Frontend：

```bash
cd web
npm test -- --run
npm run lint
npm run build
```

必须记录：

* backend test count
* frontend test count
* exact Product HEAD
* Base SHA
* changed files
* known limitations

---

# 47. Live DeepSeek Validation

因为新增了一个模型可见 Tool：

如果环境存在授权：

`DEEPSEEK_API_KEY`

必须执行至少一次真实 live knowledge smoke。

建议至少测试：

```text
故障工单应该怎么关闭？
```

并记录：

* thread_id
* run_id
* understanding
* action
* selected tool
* tool args
* knowledge result
* evidence
* final reply

另建议验证至少一个 routing negative：

```text
别人都有设备台账菜单，为什么我没有？
```

确认仍走：

`permission_query`

如果没有授权密钥：

明确记录：

`LIVE_EVAL_NOT_RUN`

Mock 不得被宣称为 live quality PASS。

---

# 48. Independent Tester Role

Developer 完成 Product HEAD 后：

冻结：

`Product HEAD`

启动独立 Tester。

Tester 不采用 Developer 的结论作为证据。

Tester必须：

* 阅读 Task Spec
* 阅读 ADR-006
* 阅读实际 diff
* 自己设计 adversarial tests
* 自己运行测试
* 验证 source code
* 验证 browser path
* 验证 Eval
* 验证 routing boundaries

Tester 报告：

```text
Decision:
PASS / FAIL

BLOCKER:
MAJOR:
MINOR:
NIT:

Base:
Product HEAD:
Tester Evidence HEAD:

Validation:
...

Adversarial findings:
...
```

Tester 可增加：

* tests/**
* Tester report

不得修改 Product implementation。

---

# 49. Astra Medium Reviewer Gate

Tester Gate 完成后：

启动：

**Astra Medium Reviewer**

Reviewer 必须独立审核：

### Architecture

* 是否真的保持 Tool architecture
* 是否无 Graph scope creep
* 是否没有新的 RAG side channel
* 是否 Knowledge 与 Evidence boundary 正确

### Retrieval

* generic retrieval
* deterministic ranking
* corpus/versioning
* chunking
* provenance
* NOT_FOUND

### Agent behavior

* C01
* C13
* C03 regression
* C05/C12 regression
* C10 regression
* C09 remains gap

### Safety

* READ_ONLY
* no path leakage
* no full document context injection
* no historical Evidence promotion
* no hardcoded query
* no fake citations

### Tests

Reviewer 不得只读取 Tester PASS。

必须检查：

* actual diff
* code
* tests
* relevant runtime path

并至少运行 focused adversarial validation。

---

# 50. Astra Medium Reviewer Output

格式：

```text
TASK-P1-011 Astra Medium Reviewer Report

Decision:
APPROVE / REQUEST_CHANGES / ESCALATE

BLOCKER:
<count>

MAJOR:
<count>

MINOR:
<count>

NIT:
<count>

Reviewed Base:
<sha>

Reviewed Product HEAD:
<sha>

Reviewed Evidence HEAD:
<sha>

Architecture:
...

Retrieval:
...

Evidence/Grounding:
...

Eval:
...

Regression:
...

Findings:
...

PM Architecture Gate:
PENDING

Merge:
PROHIBITED
```

---

# 51. Remediation Protocol

如果 Tester 或 Astra Medium Reviewer 出现：

`BLOCKER` 或 `MAJOR`

进入：

```text
Developer remediation
→ validation
→ Independent Tester rerun
→ Astra Medium Reviewer rerun
```

任何 Product code remediation 后：

之前的 Tester PASS 不再覆盖新 Product HEAD。

必须重新 Tester。

---

# 52. Repeated Failure Rule

如果：

同一根因 MAJOR 连续出现 2 次

或：

需要改变已批准架构才能解决

则：

`ESCALATE`

启动 Escalation Architect。

不要进行第三轮无边界：

* Prompt 微调
* fixture 调整
* eval case 特判
* query hardcoding

---

# 53. Hard Stop Conditions

以下任一情况立即 STOP 并返回 PM：

### Architecture

需要修改：

* LangGraph topology
* P1-006 Evidence semantics
* Grounded renderer trust model
* P1-010 Conversation semantics

### Retrieval Platform

需要新增：

* vector DB
* embeddings
* external knowledge service
* document ingestion server
* distributed knowledge infrastructure

### Product Scope

需要新增：

* Knowledge management UI
* write/update/delete API
* authentication/RBAC
* external enterprise connector

### Grounding

如果 knowledge result 无法通过现有 Grounded Response architecture 正常回答，而 Developer 想绕过 grounding：

必须 STOP。

不得 bypass。

---

# 54. Explicit Out of Scope

TASK-P1-011 不实现：

* `log_search`
* log ingestion
* incident root-cause engine
* embeddings
* vector DB
* semantic reranker
* hybrid vector retrieval
* web search
* external company knowledge connector
* Feishu/Notion/Confluence connector
* document upload
* document editor
* knowledge management UI
* knowledge ACL platform
* multi-tenant knowledge isolation
* automatic update scheduler
* crawler
* knowledge deletion scheduler
* LLM query rewrite
* LLM summarizer
* Agent Skill Runtime
* long-term user memory
* write tools
* human approval workflow
* LangGraph checkpoint/resume

---

# 55. Accepted P1-011 Limitations

以下可以作为本阶段 Known Limitations：

### Lexical retrieval

无法覆盖所有复杂语义改写。

### Synthetic corpus

目前不是企业真实知识库。

### No runtime update

知识通过 versioned repository artifact 更新。

### One primary chunk

第一版不做 multi-chunk synthesis。

### No reranking

没有 cross-encoder / LLM reranker。

### No ACL

只有基础 system scope，不是企业级 document ACL。

这些不应自动被 Reviewer 判定为 MAJOR。

除非实现与 ADR 声称不一致。

---

# 56. Mandatory Acceptance Checklist

PM handoff 前必须全部满足：

```text
[ ] main base verified
[ ] Issue created
[ ] Draft PR created
[ ] ADR-006 created
[ ] versioned corpus exists
[ ] corpus validation exists
[ ] deterministic cleaning exists
[ ] deterministic chunking exists
[ ] generic lexical retrieval exists
[ ] Chinese retrieval works
[ ] system filter works
[ ] knowledge_search registered
[ ] knowledge_search READ_ONLY
[ ] typed request/response
[ ] provenance retained
[ ] full document not injected
[ ] no source path leakage
[ ] no query hardcoding
[ ] Knowledge uses existing ToolRegistry
[ ] Knowledge uses existing review_tool_result
[ ] Knowledge produces current-run Evidence
[ ] Grounding boundary unchanged
[ ] C01 PASS in Golden v0.3
[ ] at least one additional Knowledge Golden Case PASS
[ ] Golden v0.2 unchanged
[ ] C03 still permission_query
[ ] C05/C12 still work_order_query
[ ] C10 still incident_query
[ ] C09 remains LOG_SEARCH_NOT_IMPLEMENTED
[ ] conversation + knowledge continuation tested
[ ] backend full regression PASS
[ ] frontend regression PASS
[ ] browser E2E PASS
[ ] live DeepSeek run OR LIVE_EVAL_NOT_RUN recorded
[ ] Independent Tester B0/M0
[ ] Astra Medium Reviewer APPROVE B0/M0
[ ] exact Reviewed HEAD CI PASS
[ ] PM Architecture Gate PENDING
[ ] PR remains Draft/unmerged
```

---

# 57. Definition of Done

TASK-P1-011 工程交付完成的条件：

```text
Product implementation complete

AND

ADR-006 complete

AND

Golden v0.3 complete

AND

C01 knowledge gap closed

AND

second generic knowledge scenario passes

AND

existing live-data tool routing does not regress

AND

full validation passes

AND

Independent Tester:
PASS
BLOCKER 0
MAJOR 0

AND

Astra Medium Reviewer:
APPROVE
BLOCKER 0
MAJOR 0

AND

CI PASS
```

达到后：

`STOP`

不要 Merge。

进入：

`PM Architecture Gate`

---

# 58. PM Final Handoff Format

最终只需要向 PM 返回：

```text
TASK-P1-011 — PM Architecture Gate Handoff

Base:
<sha>

Product HEAD:
<sha>

Reviewed HEAD:
<sha>

Delivery HEAD:
<sha>

Issue:
#...

PR:
#...

Architecture:
- KnowledgeRepository
- Corpus version
- Cleaning
- Chunking
- Retrieval algorithm
- knowledge_search Tool
- Evidence/Grounding integration
- ADR-006

Product Behavior:
- C01:
- C13:
- permission routing:
- work-order routing:
- incident routing:
- C09 known gap:

Knowledge Runtime:
- documents:
- chunks:
- max visible chunk:
- system scope:
- ranking:
- NOT_FOUND behavior:

Validation:
- Backend:
- Frontend:
- Browser:
- Eval:
- Live DeepSeek:

Independent Tester:
PASS/FAIL
B/M/m/N

Astra Medium Reviewer:
APPROVE/REQUEST_CHANGES/ESCALATE
B/M/m/N

Known Limitations:
...

Explicitly Not Implemented:
...

PM Architecture Gate:
PENDING

Merge:
PROHIBITED
```

---

# 59. Multi-Agent Execution Order

严格按以下顺序：

```text
PM / Architect
    ↓
Task Spec
    ↓
Developer
    ↓
Developer Report
    ↓
Independent Tester
    ↓
Tester Report
    ↓
Astra Medium Reviewer
    ↓
Reviewer Report
    ↓
PM Architecture Gate
```

不要增加没有明确职责的新 Agent。

Escalation Architect 只有满足 Stop / Escalation 条件时才启动。

---

# 60. Start Instruction

现在开始 TASK-P1-011。

第一步：

1. `git fetch`
2. 确认 `origin/main`
3. 必须确认 base 为：

```text
ac003587d036b22ff43adee69d93e9f43eb90183
```

4. 创建 GitHub Issue
5. 创建：

```text
tasks/active/TASK-P1-011-knowledge-retrieval-foundation.md
```

6. 创建：

```text
docs/adr/ADR-006-knowledge-retrieval-runtime.md
```

7. 创建：

```text
task/TASK-P1-011-dev
```

8. 创建 Draft PR
9. PR 保持 Draft
10. 开始 Developer 阶段

如果 `origin/main` 已经不是指定 Base：

不要自行选择新 Base。

STOP 并向 PM 报告：

```text
BASE_DRIFT_DETECTED
expected:
ac003587d036b22ff43adee69d93e9f43eb90183

actual:
<sha>
```
