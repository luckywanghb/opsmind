# TASK-P1-012 — Scoped Log Investigation Foundation

## 0. Task Identity

Repository:

`luckywanghb/opsmind`

Required Base:

`65abbe51df908e4166c100776170e5cc26ba4e73`

Phase:

`Phase 3 — Context, Knowledge & Investigation`

Task Type:

`HIGH RISK / ARCHITECTURE IMPACT`

PM Architecture Gate:

`REQUIRED`

Merge:

`PROHIBITED until PM approval`

Suggested branch:

`task/TASK-P1-012-dev`

Suggested task artifact:

`tasks/active/TASK-P1-012-scoped-log-investigation.md`

Required ADR:

`docs/adr/ADR-007-log-search-runtime.md`

---

# 1. Mandatory Model Governance

Read the FINAL governance baseline already committed in:

`AGENTS.md`

It is authoritative.

Do NOT create a task-level model override.

Required execution roles:

```text
Developer
Model: Luna Max
Reasoning: Max

Independent Tester
Model: Luna Max
Reasoning: Max

Reviewer
Model: Astra Low
Reasoning: Low

Delivery Reporter
Model: Luna Max
Reasoning: Max
```

PM / Architect:

```text
Model: Astra Medium
Scheduling: USER CONTROLLED
```

Codex MUST NOT automatically create or invoke a PM Agent.

Escalation Architect:

```text
Model: Astra Medium
Reasoning: Medium
```

Only trigger for:

* BLOCKER;
* architecture conflict;
* repeated MAJOR.

Hard rules:

```text
MODEL_GOVERNANCE_IMMUTABLE
NO SILENT FALLBACK
NO SUB-AGENT PM OVERRIDE
REQUIRED MODEL != ACTUAL MODEL => ROLE GATE INVALID
```

Every role report must record:

```text
Role
Required Model
Actual Model
Reasoning Effort
```

If a required model is unavailable:

```text
ROLE_MODEL_UNAVAILABLE
```

STOP.

---

# 2. Base Gate

Before doing anything:

```bash
git fetch origin
git rev-parse origin/main
```

Expected:

`65abbe51df908e4166c100776170e5cc26ba4e73`

If different:

```text
BASE_DRIFT_DETECTED

Expected:
65abbe51df908e4166c100776170e5cc26ba4e73

Actual:
<sha>
```

STOP.

Do not choose a new base automatically.

---

# 3. Historical Branch Isolation

A historical unmerged branch may still exist:

`task/TASK-P1-011-governance-correction`

It is NOT part of P1-012.

Do NOT:

* merge it;
* rebase from it;
* cherry-pick it;
* use it as P1-012 base.

P1-012 must branch directly from the verified `origin/main`.

---

# 4. Background

OpsMind currently has:

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

P1-011
Knowledge / SOP Retrieval Foundation
```

Current read-only capability surface:

```text
work_order_query
permission_query
incident_query
knowledge_search
```

Golden Suite v0.3 still contains:

```text
C09
打开 EquipFlow 页面提示 HTTP 500，帮我看看是什么问题。

KNOWN GAP:
LOG_SEARCH_NOT_IMPLEMENTED
```

P1-012 closes that gap.

---

# 5. Product Goal

Implement:

`log_search`

for bounded, read-only technical log investigation.

Target behavior:

```text
User reports concrete runtime error
        ↓
Model understands DIAGNOSE
        ↓
Model decides SEARCH
        ↓
Model selects log_search
        ↓
Scoped deterministic log retrieval
        ↓
Only relevant sanitized events
        ↓
review_tool_result
        ↓
Current-run Evidence
        ↓
GroundedResponsePlan
        ↓
Deterministic Grounded Renderer
```

Example:

```text
打开 EquipFlow 页面提示 HTTP 500，
帮我看看是什么问题。
```

Expected capability:

```text
SEARCH
→ log_search
→ relevant EquipFlow ERROR events
→ evidence containing actual component/status/exception/log message
→ grounded reply
```

The Agent must NOT receive the complete log dataset.

---

# 6. Core Context-Engineering Principle

This is the most important requirement of P1-012.

For log investigation:

```text
Full Logs != Model Context
```

The model should receive only:

```text
Current problem
+
necessary search scope
+
bounded relevant log events
```

Never:

```text
Entire log file
Entire service log history
Large arbitrary time window
All logs from all systems
```

The task follows this design principle:

```text
Need information
→ locate source
→ retrieve only relevant subset
→ sanitize / bound
→ current-run Evidence
```

Search cost and context size must remain controlled.

---

# 7. Architecture Decision

Implement:

```text
Versioned Synthetic Log Dataset
        ↓
Deterministic Loader
        ↓
Deterministic Sanitization
        ↓
LogRepository
        ↓
ScopedLogSearchService
        ↓
log_search
        ↓
Existing ToolRegistry
        ↓
Existing review_tool_result
        ↓
Existing Evidence
        ↓
Existing Grounding
```

Suggested domain:

```text
src/opsmind/logs/
    __init__.py
    models.py
    repository.py
    sanitizer.py
    retrieval.py
    tool.py
    data/
        manifest.json
        events.jsonl
```

Equivalent clean decomposition is acceptable.

---

# 8. Explicit Non-Goals

P1-012 is NOT a general observability platform.

Do NOT implement:

```text
Elasticsearch
OpenSearch
Loki
Splunk
ClickHouse
Datadog
Grafana integration
MCP log server
external API connector
real enterprise logs
streaming logs
live tail
log ingestion pipeline
log upload
log management UI
log download
root-cause engine
LLM log summarizer
vector log retrieval
embedding search
regex query language
Lucene / KQL parser
write remediation
service restart
database restart
configuration change
incident mutation
```

Do NOT add an Artifact Store platform in this task.

The selected result is intentionally small enough to remain inside the
existing typed Tool/Evidence boundary.

---

# 9. No Graph Change

Do NOT modify LangGraph topology.

The existing loop already supports:

```text
decide_action
→ select_tool
→ execute_tool
→ review_tool_result
→ decide_action
```

Do NOT add:

```text
log_node
diagnostic_node
investigation_graph
log_agent
root_cause_node
```

If Developer believes a graph change is required:

```text
STOP
→ PM Architecture Gate
```

---

# 10. No Grounding Change

P1-006 trust semantics must remain unchanged.

Log output must flow through:

```text
log_search
→ typed ToolResponse
→ review_tool_result
→ current-run Evidence
→ GroundedResponsePlan
→ deterministic renderer
```

Forbidden:

```text
log result → direct LLM answer
log result → response.message
log result → free-form root-cause prose
```

Do not add a log-specific final-answer renderer.

Existing generic grounding must remain authoritative.

If the current grounding system cannot safely render bounded nested log
fields without architecture changes:

```text
STOP
→ PM Architecture Gate
```

Do not bypass it.

---

# 11. LogRepository

Create a backend-neutral:

`LogRepository`

Responsibilities:

* expose validated synthetic log events;
* support deterministic candidate retrieval;
* isolate storage from Agent runtime;
* return detached/immutable data;
* know nothing about LangGraph;
* know nothing about model prompts;
* know nothing about final answers.

Current implementation may be:

`LocalLogRepository`

Future backends should be able to replace it without changing:

`log_search`

tool contract.

---

# 12. Versioned Synthetic Log Dataset

Create a repository-owned deterministic dataset.

Recommended:

```text
src/opsmind/logs/data/manifest.json
src/opsmind/logs/data/events.jsonl
```

Manifest should contain at least:

```text
schema_version
dataset_id
dataset_version
source_file
```

No external network.

No real user/company data.

All content must remain obviously synthetic.

Suggested dataset size:

```text
15–40 events
```

Large enough to contain noise and distinct scenarios.

Do not create a dataset where every event is relevant.

---

# 13. Synthetic Log Scenarios

At least three distinguishable technical scenarios are required.

## Scenario A — EquipFlow HTTP 500

Must support C09:

```text
打开 EquipFlow 页面提示 HTTP 500，
帮我看看是什么问题。
```

Include several related events such as:

```text
system:
EquipFlow

component:
web-gateway / workflow-api

http_status:
500

trace_id:
TRC-EF-500-001
```

A source event should expose a concrete structured technical error, for
example:

```text
exception_type:
DatabasePoolTimeoutError
```

and a bounded log message semantically similar to:

```text
database connection acquisition timed out
```

The exact synthetic wording is Developer-owned.

Important:

The source log itself must contain the technical fact.

Do NOT have the Python harness infer:

```text
root_cause = database failure
```

from arbitrary co-occurrence.

---

## Scenario B — QualityHub Technical Error

Example user query:

```text
QualityHub 导出报表提示 QH-RPT-502，
帮我查一下日志。
```

Dataset should contain:

```text
system_id = QualityHub
error_code = QH-RPT-502
```

with a different component / trace / exception.

Purpose:

prove `log_search` is generic and not a C09 fixture.

---

## Scenario C — Noise / Unrelated Events

Add:

* normal INFO events;
* unrelated WARN events;
* different systems;
* different traces;
* unrelated error codes.

Purpose:

prove scope and ranking.

---

# 14. Log Event Model

Suggested source model:

```text
LogEvent
```

Fields should be bounded and typed.

Recommended:

```text
event_id
timestamp
system_id
site_id | null
component
severity
trace_id | null
request_path | null
http_status | null
error_code | null
exception_type | null
message
```

Severity should use a small enum such as:

```text
DEBUG
INFO
WARN
ERROR
```

Use timezone-aware ISO timestamps.

Do NOT reuse or modify the P1-011 `updated_at` validator merely to solve
the accepted P1-011 timezone MINOR.

P1-011 technical debt remains out of scope.

---

# 15. Dataset Validation

LocalLogRepository must fail closed on malformed repository data.

Test at least:

* malformed JSONL;
* non-object event;
* duplicate event_id;
* invalid timestamp;
* naive timestamp if timezone-awareness is required;
* invalid severity;
* empty required field;
* oversized field;
* oversized source file;
* too many events;
* missing source file;
* absolute path;
* `..` traversal;
* Windows drive path;
* symlink escape if applicable;
* malformed UTF-8.

Error returned outside the repository should be generic, e.g.:

```text
LOG_DATASET_INVALID
```

Do not leak:

* local absolute path;
* raw offending log line;
* exception traceback.

---

# 16. Deterministic Log Sanitization

Logs are untrusted source data.

Implement deterministic sanitization before any event becomes tool-visible.

At minimum redact obvious secrets such as values associated with:

```text
Authorization
Bearer
api_key
apikey
password
passwd
token
access_token
session
cookie
```

Example:

```text
Authorization: Bearer abc123secret
```

must become something like:

```text
Authorization: Bearer [REDACTED]
```

Sanitization must be:

* deterministic;
* provider-free;
* bounded;
* performed before model context;
* performed before Evidence;
* performed before run persistence.

Also sanitize unsafe control characters / line breaks as appropriate.

Do NOT claim this is an enterprise-grade DLP system.

It is a bounded first-line safety layer.

---

# 17. Raw Log Boundary

The raw synthetic log dataset may exist as repository data.

But it must NEVER enter:

```text
model prompt
review context
Evidence
Agent state
conversation checkpoint
Run API
Eval result
browser response
final response
```

Only sanitized selected events may cross the Tool boundary.

---

# 18. LogSearchRequest

Recommended typed contract:

```text
LogSearchRequest

query: str | None
system_id: str | None
site_id: str | None
trace_id: str | None
error_code: str | None
```

Bounds:

```text
query <= 256 chars
system_id <= 128
site_id <= 128
trace_id <= 128
error_code <= 128
```

Whitespace-only values invalid.

Do NOT expose first-version parameters such as:

```text
limit
offset
page
regex
query_language
index
cluster
sort
ranking_algorithm
max_tokens
```

These are runtime policy.

---

# 19. Search-Scope Validation

Prevent broad uncontrolled search.

A valid request should require either:

```text
trace_id
```

OR:

```text
system_id
+
(query OR error_code)
```

Examples:

Valid:

```text
system_id=EquipFlow
query="HTTP 500"
```

Valid:

```text
system_id=QualityHub
error_code="QH-RPT-502"
```

Valid:

```text
trace_id="TRC-EF-500-001"
```

Invalid:

```text
system_id=EquipFlow
```

only.

Invalid:

```text
query="error"
```

with no system and no trace.

This is a deterministic cost/scope safety constraint,
not business routing.

---

# 20. No Regex / Query-Language Execution

`query` is literal search text.

Do NOT interpret it as:

* regex;
* SQL;
* Lucene;
* KQL;
* shell;
* Python expression.

Characters such as:

```text
.*
[
]
(
)
|
?
+
```

must not gain execution semantics.

---

# 21. ScopedLogSearchService

Implement a provider-free deterministic search service.

Suggested:

`ScopedLogSearchService`

Responsibilities:

1. apply structured scope;
2. search sanitized candidate events;
3. rank relevant events;
4. return bounded matches.

Recommended scope order:

```text
system_id / site_id filter
→ exact trace_id/error_code constraints
→ lexical query ranking
→ deterministic selection
```

---

# 22. Lexical Matching

Search should support:

* English;
* numbers;
* identifiers;
* HTTP status;
* error codes;
* Chinese text if present;
* Unicode normalization;
* case-insensitive comparison.

Simple deterministic tokenization is sufficient.

Possible searchable fields:

```text
system_id
component
severity
trace_id
request_path
http_status
error_code
exception_type
message
```

For structured fields, expose normalized searchable representations.

Example:

```text
http_status = 500
```

should allow:

```text
"HTTP 500"
```

to retrieve the event.

Do not hardcode that query.

---

# 23. Ranking

Ranking must be deterministic.

A reasonable approach:

```text
exact structured match boost
+
literal phrase support
+
token overlap
```

Tie-break by stable event identity / timestamp.

Exact algorithm may vary.

Requirements:

```text
same dataset + same request
→ same events
→ same order
```

No model-based reranking.

No embeddings.

No query-specific mappings.

---

# 24. Bounded Result

Tool-visible result must contain no more than:

```text
5 events
```

Recommended constant:

```text
MAX_RETURNED_EVENTS = 5
```

Do NOT let the model change it.

Each visible message should be bounded, e.g.:

```text
<= 600 chars
```

Total serialized ToolResponse must remain comfortably inside the existing
Evidence item limit.

Target:

```text
< 12 KB
```

Do not approach the existing 16 KB evidence ceiling.

---

# 25. LogSearchResponse

Recommended:

```text
LogSearchResponse

result_status

matched_count
returned_count
truncated

event_ids
system_ids
trace_ids
components
http_statuses
error_codes
exception_types

events
```

Where each `events[]` item is a bounded sanitized event projection.

Mechanical aggregate fields are allowed because they are direct deterministic
projections of returned source events.

They are NOT diagnostic conclusions.

---

# 26. Response Consistency

FOUND:

```text
returned_count > 0
returned_count == len(events)
matched_count >= returned_count
```

Aggregate values must correspond to actual returned events.

Example:

```text
error_codes
```

must be the stable unique error codes from returned events.

NOT_FOUND:

```text
matched_count = 0
returned_count = 0
truncated = false
events = []
aggregate lists = []
```

Do not fabricate:

```text
component
trace_id
error_code
exception
```

for NOT_FOUND.

---

# 27. No Root-Cause Fabrication

This task is log retrieval, not an autonomous RCA engine.

Do NOT add a model or Python field such as:

```text
root_cause
likely_root_cause
recommended_fix
```

unless that exact field is directly supplied as structured source data.

Current synthetic dataset should not rely on such a field.

A grounded response can report source facts such as:

```text
组件
异常类型
HTTP 状态
错误码
日志消息
trace_id
```

but must not silently transform correlation into proven causation.

---

# 28. log_search Tool Description

Tool description must clearly distinguish this capability.

Semantics should be close to:

```text
搜索当前技术故障相关的受限运行日志，用于分析具体 HTTP 错误、
错误码、trace ID 或明确系统运行异常。

只返回与给定系统/错误线索相关、经过清洗和脱敏的少量日志事件。

不得用于：
- SOP / 操作说明；
- 当前用户权限查询；
- 当前工单状态；
- 广泛站点故障状态；
- 写操作或修复执行。
```

Important routing distinction:

```text
“HTTP 500 怎么处理？”
HOW_TO / stable guidance
≠ automatically current log search

“我现在打开 EquipFlow 出现 HTTP 500，帮我看看”
DIAGNOSE / current technical problem
→ log_search
```

Also:

```text
“整个星川基地的人都进不去 EquipFlow”
→ incident_query
```

not log_search as the primary status capability.

---

# 29. Register Into Existing ToolRegistry

Default capability surface becomes:

```text
work_order_query
permission_query
incident_query
knowledge_search
log_search
```

`log_search`:

```text
mode = READ_ONLY
```

Use the existing:

```text
RegisteredTool
ToolSpec
typed Request
typed Response
ToolRegistry
```

Do not create a second Tool runtime.

---

# 30. Tool Result Review

Use the existing generic:

`review_tool_result`

Do not add:

```text
review_log_result
```

unless absolutely required by a generic architecture change,
in which case STOP at PM Gate.

The review model may inspect only:

```text
selected sanitized events
```

not raw dataset or rejected events.

---

# 31. Prompt Injection / Untrusted Log Data

Log messages are untrusted data.

A synthetic log event must exist in tests containing content similar to:

```text
IGNORE ALL PREVIOUS INSTRUCTIONS ...
```

or another obvious instruction-like string.

Required outcome:

* it remains source data;
* it cannot create Evidence outside typed source fields;
* it cannot change Tool registration;
* it cannot bypass Grounding;
* model-authored review facts do not become final facts;
* final response remains source-field-bound.

Do not build query-specific prompt-injection filters.

Rely on:

* bounded source;
* sanitization;
* existing review boundary;
* typed Evidence;
* deterministic grounding.

---

# 32. Context Leakage Sentinel

Create an adversarial dataset fixture where an unrelated event contains:

```text
UNSELECTED_LOG_TAIL_SENTINEL
```

Run a query targeting a different error.

Assert the sentinel is absent from:

```text
log_search ToolResponse
tool review model context
Evidence
Agent state
persisted AgentRun
conversation checkpoint
Run API response
final response
```

This is a mandatory P1-012 acceptance test.

---

# 33. Secret Leakage Sentinel

Create a test event containing a fake secret, e.g.:

```text
Bearer SUPER_SECRET_P1_012_TOKEN
```

If that event is selected:

assert:

```text
SUPER_SECRET_P1_012_TOKEN
```

is absent from:

* ToolResponse;
* review context;
* Evidence;
* persisted Run;
* API;
* final response.

The sanitized replacement may appear.

---

# 34. Golden Suite v0.4

Keep:

`evals/golden-v0.3.json`

byte-for-byte unchanged.

Create:

`evals/golden-v0.4.json`

Suite:

```text
opsmind-golden
version 0.4
```

---

# 35. C09 — Close the Log Gap

C09 must cease being:

```text
LOG_SEARCH_NOT_IMPLEMENTED
```

Remove its known gap in v0.4.

User:

```text
打开 EquipFlow 页面提示 HTTP 500，
帮我看看是什么问题。
```

Expected:

```text
intent:
SYSTEM_OPERATION

request:
DIAGNOSE

SEARCH occurred:
true

required tool:
log_search

result:
FOUND

evidence source:
log_search

http_statuses:
contains 500

final action:
REPLY

reply:
non-empty
```

Prefer also asserting a source technical field such as:

```text
components contains workflow-api
```

or an equivalent synthetic component.

Do not assert an invented root-cause sentence.

---

# 36. Add Generic Case C14

Add a new case proving the runtime is not C09-specific.

Suggested:

```text
C14 — QualityHub report export runtime error
```

User:

```text
QualityHub 导出报表提示 QH-RPT-502，
帮我查一下日志。
```

Expected:

```text
SYSTEM_OPERATION
DIAGNOSE
SEARCH
log_search
FOUND
error_codes contains QH-RPT-502
evidence_source_present log_search
REPLY
reply_nonempty
```

Exact synthetic technical details may be Developer-owned.

---

# 37. Preserve Existing Routing

Golden v0.4 must preserve existing expected semantics for:

```text
C01
→ knowledge_search

C03
→ permission_query

C05
→ work_order_query

C06
→ ASK_USER

C10
→ incident_query + TRANSFER_HUMAN

C11
→ no privileged write

C12
→ same-thread continuation + current work-order evidence

C13
→ knowledge_search
```

Adding logs must not cause tool-space regression.

---

# 38. Important C06 Regression

Existing C06:

```text
我的工单提交失败了，帮我看看。
```

has insufficient concrete scope.

It must NOT suddenly become:

```text
search every log in every system
```

Expected remains:

```text
ASK_USER
tool calls = 0
```

This is an important scope-control test.

---

# 39. Important C10 Regression

Existing broad outage:

```text
今天整个星川基地的人都进不去 EquipFlow。
```

must remain:

```text
incident_query
```

and not drift to:

```text
log_search
```

The user is asking about broad current operational state,
not a narrow technical trace.

---

# 40. Adversarial Routing Matrix

Independent Tester must validate at minimum:

### Stable SOP

```text
设备台账怎么导出？
→ knowledge_search
```

### Current permission

```text
为什么 U10023 没有设备台账权限？
→ permission_query
```

### Work-order state

```text
WO20260001现在到谁了？
→ work_order_query
```

### Broad outage

```text
整个星川基地的人都进不去 EquipFlow
→ incident_query
```

### Concrete technical error

```text
EquipFlow 页面现在报 HTTP 500，
帮我查下是什么问题。
→ log_search
```

### Concrete error code

```text
QualityHub 报 QH-RPT-502，
帮我查日志。
→ log_search
```

### Insufficient scope

```text
系统报错了，帮我查一下。
→ ASK_USER
```

not broad log search.

---

# 41. Generic Evaluator Extension

Current evaluators operate on generic Evidence fields.

If Golden v0.4 needs nested event-field assertions, prefer one of:

1. use mechanical top-level aggregate fields such as:

```text
http_statuses
error_codes
components
```

or

2. extend evaluator field-path support generically.

Do NOT add:

```text
if case_id == "C09"
if source == "log_search" then special-case
```

Any evaluator extension must benefit arbitrary nested typed Evidence.

Prefer option 1 unless option 2 is clearly necessary.

---

# 42. Conversation + Log Continuity

Add a two-turn integration case outside or inside the Golden suite.

Turn 1:

```text
打开 EquipFlow 页面提示 HTTP 500，
帮我看看是什么问题。
```

Turn 2:

```text
那具体是哪个组件报错？
```

Requirements:

```text
same thread_id

fresh request_id
fresh run_id

second run performs log_search again

second run receives fresh current-run log Evidence

historical E1 is NOT restored as current Evidence

previous assistant answer is NOT promoted into Evidence
```

The previous user query/history may help reconstruct the search problem.

But factual response must still come from the second run's fresh log search.

---

# 43. Search Efficiency

Do not force multi-search behavior merely to look “agentic”.

A single search may be sufficient.

Existing Agent loop remains free to run another materially different search if
evidence is insufficient.

C09 should normally complete within:

```text
<= 2 total tool calls
```

Prefer one.

Do not repeatedly search the same signature.

Existing duplicate successful-call protection must remain effective.

---

# 44. No Hardcoding

Source scan and behavioral tests must demonstrate absence of:

```text
if "HTTP 500" in query: return ...
if "QH-RPT-502" ...
if case_id == "C09"
if case_id == "C14"
```

No:

* query phrase routing table;
* fixture mapping;
* Golden-case branch;
* error-text branch in Agent graph.

The synthetic dataset may naturally contain:

```text
HTTP 500
QH-RPT-502
```

That is data, not runtime hardcoding.

---

# 45. Retrieval Tests

Developer and Tester coverage should include:

* English query;
* uppercase/lowercase;
* HTTP status;
* numeric identifiers;
* error code;
* trace ID;
* Chinese text;
* Unicode normalization;
* punctuation;
* regex-looking characters treated literally;
* system filtering;
* site filtering;
* incorrect system;
* unknown trace;
* unknown error code;
* deterministic ranking;
* deterministic tie break;
* result cap;
* truncated flag;
* NOT_FOUND;
* duplicate IDs;
* malformed corpus;
* secret redaction;
* control characters;
* path traversal;
* no raw path leakage.

---

# 46. Response Contract Tests

Test:

```text
FOUND
```

requires valid events and consistent aggregates.

Test:

```text
NOT_FOUND
```

contains no fabricated event facts.

Attempt forged mismatches such as:

```text
events http_status = 500
http_statuses = [200]
```

must fail typed response validation.

Attempt:

```text
returned_count != len(events)
```

must fail.

---

# 47. Grounding Tests

Use real existing grounding runtime.

Verify a grounded plan may select:

```text
E1.http_statuses
E1.components
E1.exception_types
```

and, where supported:

```text
E1.events.0.message
E1.events.0.trace_id
```

Output values must come from typed source data.

Attempt model-forged factual review prose:

```text
ROOT_CAUSE_IS_MAGIC
```

must NOT become final factual output unless that literal source value exists.

Attempt nonexistent evidence reference:

```text
E99
```

must fail closed.

---

# 48. No Raw Log Persistence

Persisted AgentRun may contain:

```text
selected sanitized Evidence
```

because it is part of the existing current-run audit record.

It must not contain:

```text
full synthetic dataset
unselected events
raw unsanitized selected event
secret before redaction
source_file
absolute source path
loader exception
```

---

# 49. Conversation Persistence Boundary

Conversation checkpoint must not gain:

```text
raw logs
historical log Evidence
full events
```

Keep P1-010 semantics unchanged.

A later turn may retain bounded conversational task/context,
but must obtain new current-run Evidence before making factual claims.

---

# 50. Browser Acceptance

Use:

* real FastAPI app;
* real Vite UI;
* real default ToolRegistry;
* real LocalLogRepository;
* real ScopedLogSearchService;
* deterministic test-only model decisions.

Browser flow:

```text
/chat

User:
打开 EquipFlow 页面提示 HTTP 500，
帮我看看是什么问题。
```

Verify UI shows:

```text
SEARCH
log_search
log_search: found
review
REPLY
```

and nonempty grounded answer.

Run API must show:

```text
SUCCEEDED
source = log_search
result_status = found
current-run Evidence
```

Verify:

```text
returned events <= 5
```

and no:

```text
source_file
internal path
raw secret
UNSELECTED_LOG_TAIL_SENTINEL
```

---

# 51. Eval Runtime Acceptance

Golden v0.4 must run through the same:

```text
AgentExecutionService
→ OpsAgentRuntime
→ ToolRegistry
→ log_search
```

as Chat.

Forbidden:

```text
eval-only log result
fake eval log evidence
C09 response injection
special evaluator runtime branch
```

---

# 52. Eval UI

The existing Evaluation UI should continue working with Golden v0.4.

Prefer zero frontend product changes if suite version/display is already
dynamic.

If a small generic compatibility update is required, it is allowed.

Do not create a Log UI.

---

# 53. Live DeepSeek Smoke

If an authorized:

`DEEPSEEK_API_KEY`

is available, run live semantic smoke tests.

Required priority:

### Positive

```text
C09
EquipFlow HTTP 500
→ log_search
```

### Negative routing

Prefer:

```text
C10
broad outage
→ incident_query
```

and/or:

```text
C06
insufficient detail
→ ASK_USER
```

If no key:

```text
LIVE_EVAL_NOT_RUN
```

Do not classify deterministic mocked routing as live quality PASS.

---

# 54. ADR-007

Create:

`docs/adr/ADR-007-log-search-runtime.md`

Status during implementation:

```text
Implemented for TASK-P1-012.
PM Architecture Gate pending.
```

ADR must explicitly decide:

1. Why log investigation is a registered Tool, not a new graph.
2. Why full logs never enter model context.
3. Why repository/service boundaries exist.
4. Why the first version uses local synthetic logs.
5. Why retrieval is deterministic and provider-free.
6. Request scope requirements.
7. No regex/query language.
8. Result-size limits.
9. Sanitization/redaction boundary.
10. Raw logs vs sanitized selected Evidence.
11. Why no Artifact Store yet.
12. Why no LLM log summarizer.
13. Why no root-cause field is inferred.
14. Current-run Evidence trust boundary.
15. Conversation re-search semantics.
16. Routing distinction between:

    * knowledge;
    * permission;
    * work order;
    * incident;
    * logs.
17. Future replaceability with real log backends.
18. Limitations and future evolution.

Do not mark ADR Accepted before PM approval.

---

# 55. Future Backend Upgrade Boundary

ADR should make clear that future:

```text
OpenSearch
Loki
Splunk
Datadog
MCP log service
internal LogCenter API
```

could replace:

`LocalLogRepository / ScopedLogSearchService`

without changing the Agent-level:

`LogSearchRequest / LogSearchResponse`

contract unless a later Architecture Gate approves a new contract.

---

# 56. Documentation

Update as applicable:

```text
README.md
docs/ARCHITECTURE.md
docs/AGENT_KERNEL.md
docs/API.md
```

Document:

```text
default READ_ONLY tools = 5
```

and:

`log_search`

scope.

Also correct any stale P1-011 architecture status encountered in current
architecture documentation so that P1-011 is represented as accepted.

Do NOT alter historical task reports.

---

# 57. Known P1-011 Minor

Do NOT opportunistically modify:

`src/opsmind/knowledge/models.py`

to fix the accepted P1-011 explicit-offset `updated_at` MINOR.

That debt is not part of P1-012.

If a shared timestamp architecture change becomes genuinely necessary:

```text
STOP
→ PM Architecture Gate
```

---

# 58. Developer Validation

Developer must run:

```bash
uv run --frozen pytest
uv run --frozen ruff check .
uv run --frozen mypy src
uv lock --check
git diff --check
```

Frontend:

```bash
cd web
npm test -- --run
npm run lint
npm run build
```

Report exact:

```text
Base SHA
Product HEAD
changed files
backend test count
frontend test count
live eval status
known limitations
```

Developer report must include:

```text
Role:
Developer

Required Model:
Luna Max

Actual Model:
<actual>

Reasoning:
Max
```

---

# 59. Independent Tester Gate

After Developer freezes Product HEAD:

start a separate:

```text
Independent Tester
Model: Luna Max
Reasoning: Max
```

Tester must independently inspect:

* task;
* ADR-007;
* actual Base→Product diff;
* logs domain;
* sanitizer;
* retrieval;
* typed contract;
* ToolRegistry;
* review/Evidence;
* grounding;
* conversation;
* Eval;
* UI compatibility.

Tester may add:

* tester-only tests;
* test browser fixtures;
* reports.

Tester must NOT modify product implementation.

Required report:

```text
PASS / FAIL

BLOCKER:
<n>

MAJOR:
<n>

MINOR:
<n>

NIT:
<n>

Base:
<sha>

Product HEAD:
<sha>

Tester Evidence HEAD:
<sha>
```

---

# 60. Tester Mandatory Adversarial Coverage

Independent Tester must independently verify:

### Scope safety

Broad requests do not search all logs.

### Tool routing

Knowledge / permission / workflow / incident / log remain differentiated.

### Result bounding

No more than 5 events.

### Sanitization

Fake bearer/token/password values do not leak.

### Context leakage

`UNSELECTED_LOG_TAIL_SENTINEL` never crosses the retrieval boundary.

### Prompt injection

Instruction-like log data remains untrusted.

### Grounding

No model review fabrication becomes final fact.

### Persistence

No raw or unselected logs persist.

### Hardcode

No C09/C14 phrase mapping.

### Determinism

Same search = same result/order.

---

# 61. Reviewer Gate

After valid Independent Tester PASS:

start:

```text
Reviewer
Model: Astra Low
Reasoning: Low
```

No Astra Medium.

Reviewer must independently inspect architecture and focused tests.

Required decision:

```text
APPROVE
REQUEST_CHANGES
ESCALATE
```

Report:

```text
BLOCKER
MAJOR
MINOR
NIT
```

Reviewer must explicitly assess:

* log search architecture;
* context bounding;
* secret sanitization;
* evidence/grounding;
* no root-cause fabrication;
* routing regression;
* Golden v0.4;
* raw-log leakage;
* scope creep.

Reviewer cannot substitute for Independent Tester.

---

# 62. Remediation Loop

If Tester or Reviewer finds:

```text
BLOCKER > 0
or
MAJOR > 0
```

then:

```text
Developer — Luna Max / Max
→ remediation
→ Developer validation
→ Independent Tester — Luna Max / Max rerun
→ Reviewer — Astra Low / Low rerun
```

Any product implementation change invalidates the previous Tester/Reviewer
product gate.

---

# 63. Escalation

Trigger:

`Escalation Architect — Astra Medium / Medium`

only if:

* architecture change is required;
* same root-cause MAJOR occurs twice;
* BLOCKER requires architecture decision;
* required hard stop is reached.

Do NOT use Escalation Architect for ordinary implementation bugs.

Do NOT perform a third round of:

* prompt tweaking;
* fixture hardcoding;
* query-specific special cases.

---

# 64. Hard Stops

STOP and return to PM if implementation requires:

```text
LangGraph topology change
P1-006 grounding/trust change
P1-010 conversation semantics change
Artifact Store platform
external log backend
MCP log integration
vector/embedding search
LLM summarizer
root-cause model
write/remediation tool
log admin UI
log streaming/tailing
raw-log persistence
broad unbounded search
```

Do not silently expand scope.

---

# 65. Accepted First-Version Limitations

The following are acceptable and should NOT automatically become MAJOR:

* synthetic local logs only;
* lexical/structured matching only;
* no semantic log search;
* no external LogCenter;
* no distributed search backend;
* no arbitrary query language;
* max five returned events;
* deterministic sanitizer is not enterprise DLP;
* no autonomous RCA;
* no remediation;
* no Artifact Store;
* no Log UI.

Reviewer may still report implementation-specific defects.

---

# 66. Delivery Reporter

After valid:

```text
Independent Tester PASS B0/M0
+
Astra Low Reviewer APPROVE B0/M0
```

start:

```text
Delivery Reporter
Model: Luna Max
Reasoning: Max
```

Delivery Reporter must only normalize:

* Base;
* Product HEAD;
* Tester Evidence HEAD;
* Reviewed HEAD;
* Delivery HEAD;
* test counts;
* browser evidence;
* live eval status;
* CI;
* known limitations;
* PR status.

It must not make architecture decisions.

---

# 67. PM Architecture Gate

PR must remain:

```text
Draft
Unmerged
```

until PM approval.

Required return condition:

```text
Implementation complete

ADR-007 complete

Golden v0.4 complete

C09 PASS

C14 PASS

C06 regression PASS

C10 regression PASS

context leakage PASS

secret leakage PASS

browser PASS

full backend PASS

frontend PASS

Independent Tester:
PASS B0/M0

Reviewer:
APPROVE B0/M0

exact Reviewed/Delivery HEAD:
CI PASS
```

Then:

```text
STOP
→ PM Architecture Gate
```

Do NOT merge.

---

# 68. Required PM Handoff Format

Return:

```text
TASK-P1-012 — PM Architecture Gate Handoff

Issue:
#<number>

Draft PR:
#<number>

Base:
65abbe51df908e4166c100776170e5cc26ba4e73

Product HEAD:
<sha>

Tester Evidence HEAD:
<sha>

Reviewed HEAD:
<sha>

Delivery HEAD:
<sha>

Implementation:
- LogRepository
- versioned synthetic log dataset
- deterministic sanitization
- ScopedLogSearchService
- READ_ONLY log_search
- existing Evidence/Grounding pipeline
- ADR-007

Golden:
v0.4

C09:
PASS / FAIL

C14:
PASS / FAIL

C06 regression:
PASS / FAIL

C10 regression:
PASS / FAIL

Context leakage:
PASS / FAIL

Secret leakage:
PASS / FAIL

Independent Tester:
Luna Max / Max
PASS/FAIL — B?/M?/m?/N?

Reviewer:
Astra Low / Low
APPROVE/REQUEST_CHANGES/ESCALATE — B?/M?/m?/N?

Live DeepSeek:
PASS details
or
LIVE_EVAL_NOT_RUN

Backend:
<n> passed

Frontend:
<n> passed

Browser:
PASS / FAIL

CI:
Python PASS/FAIL
Web PASS/FAIL

ADR-007:
Implemented — PM Gate pending

Known limitations:
...

PM Architecture Gate:
PENDING

Merge:
PROHIBITED
```

STOP.

---

# 69. Start Instructions

Execute in this order:

1. Read `AGENTS.md`.
2. Verify FINAL model governance.
3. `git fetch origin`.
4. Verify exact required base.
5. Confirm P1-011 historical correction branch is ignored.
6. Create P1-012 GitHub Issue.
7. Create active task artifact.
8. Create ADR-007 with PM Gate pending.
9. Create branch:

```text
task/TASK-P1-012-dev
```

10. Create Draft PR.
11. Keep PR Draft.
12. Start exactly one:

```text
Developer
Luna Max
Reasoning Max
```

13. Implement P1-012.
14. Run Developer validation.
15. Freeze Product HEAD.
16. Run separate Independent Tester.
17. Run Astra Low Reviewer.
18. Run Luna Max Delivery Reporter.
19. Return to PM Architecture Gate.
20. Do NOT merge.
