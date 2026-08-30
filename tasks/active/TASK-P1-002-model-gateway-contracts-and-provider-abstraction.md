# TASK-P1-002 — Model Gateway Contracts & Provider Abstraction

## Status

IN_PROGRESS

## Risk

MEDIUM

## Goal

为 OpsMind 建立统一、可测试、供应商无关的 Model Gateway，使后续所有 Agent Node 只能通过逻辑模型配置调用模型，而不能直接依赖 DeepSeek、OpenAI、Anthropic 等具体 Provider SDK。

本任务只建立：

* Model contracts
* Model profiles
* Provider abstraction
* Gateway routing
* Mock provider
* Observability metadata
* Tests

**本任务不接真实 DeepSeek API，不实现 LangGraph，不实现业务 Prompt。**

---

# 1. Why

OpsMind 后续至少会有以下 Model-driven 节点：

```text
understand_request
decide_action
select_tool
review_tool_result
compose_clarification
compose_reply
build_handoff
```

这些节点不能分别实例化具体 Provider Client。

正确关系应为：

```text
Agent Node
    ↓
Model Gateway
    ↓
Logical Profile
    ↓
Provider Adapter
    ↓
Concrete Model
```

例如未来：

```text
cheap
  ↓
DeepSeek

strong
  ↓
GPT / other stronger model
```

而 Agent Node 无需知道实际供应商和模型名称。

---

# 2. Required package structure

建议新增：

```text
src/opsmind/models/
├── __init__.py
├── contracts.py
├── gateway.py
├── providers/
│   ├── __init__.py
│   ├── base.py
│   └── mock.py
└── errors.py
```

如 Developer 有明显更合理的小范围拆分，可调整文件名称，但不得改变本 Task 的架构边界。

---

# 3. ModelProfile

定义：

```python
class ModelProfile(StrEnum):
```

第一版只包含：

```text
CHEAP
STRONG
FALLBACK
```

这里是逻辑 Profile，而不是模型名称。

禁止：

```text
DEEPSEEK_V4
GPT_5
CLAUDE
```

这类具体模型进入 Agent 业务 Contract。

---

# 4. ModelTask

定义 Agent 当前调用模型的用途。

建议：

```python
class ModelTask(StrEnum):
```

包含：

```text
REQUEST_UNDERSTANDING
ACTION_DECISION
TOOL_SELECTION
TOOL_RESULT_REVIEW
CLARIFICATION
RESPONSE_GENERATION
HANDOFF_GENERATION
```

ModelTask 主要用于：

* tracing；
* metrics；
* eval；
* 后续模型路由；
* 成本分析。

它**不能被 Gateway 用来硬编码业务判断**。

禁止类似：

```python
if task == ACTION_DECISION:
    use_provider_x()
```

除非未来有经过 Eval 验证的显式配置策略。

---

# 5. ModelMessage

建立供应商无关消息结构。

建议：

```python
class ModelRole(StrEnum):
    SYSTEM
    USER
    ASSISTANT
    TOOL
```

以及：

```python
class ModelMessage(BaseModel):
    role: ModelRole
    content: str
```

V0.1 不需要复制 OpenAI/DeepSeek 的完整 Message Schema。

保持最小 Contract。

---

# 6. ModelRequest

建议建立：

```python
class ModelRequest(BaseModel):
    task: ModelTask
    profile: ModelProfile
    messages: list[ModelMessage]
    metadata: dict[str, JsonValue]
```

其中：

### task

本次模型调用用途。

### profile

希望使用的逻辑模型档位。

### messages

当前模型输入。

### metadata

用于 tracing / debug / eval。

例如：

```json
{
  "thread_id": "thread-123",
  "node": "understand_request"
}
```

metadata 不应该影响业务逻辑。

---

# 7. ModelResponse

建立统一模型返回结构。

至少包含：

```text
content
provider
model
finish_reason
usage
latency_ms
request_id
```

建议：

```python
class ModelUsage(BaseModel):
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
```

以及：

```python
class ModelResponse(BaseModel):
    content: str
    provider: str
    model: str
    finish_reason: str | None
    usage: ModelUsage | None
    latency_ms: float | None
    request_id: str | None
```

要求：

* token 字段不得出现负值；
* latency 不得为 NaN / Infinity；
* Provider 缺少这些信息时允许为 `None`。

---

# 8. Structured Output

OpsMind 后续大量节点要求模型输出 Pydantic Schema，例如：

```text
RequestUnderstanding
Decision
ToolSelection
ToolResultReview
```

所以 Gateway 必须从第一版支持 structured output。

建议接口形式：

```python
T = TypeVar("T", bound=BaseModel)

async def invoke_structured(
    request: ModelRequest,
    response_model: type[T],
) -> T:
    ...
```

或者返回：

```python
StructuredModelResponse[T]
```

如果采用后一种方式，可以同时保存：

```text
parsed
raw_response
```

但不要为了未来需求引入过度复杂的泛型层次。

核心要求：

> 调用方能够提供一个 Pydantic Model，并拿到已经验证过的该 Model 实例。

Invalid structured output 必须形成明确异常。

不得默默返回未经验证的 dict。

---

# 9. Provider abstraction

建立统一 Provider Protocol / ABC。

例如：

```python
class ModelProvider(Protocol):

    async def invoke(
        self,
        request: ModelRequest,
        *,
        model: str,
    ) -> ModelResponse:
        ...

    async def invoke_structured(
        self,
        request: ModelRequest,
        response_model: type[T],
        *,
        model: str,
    ) -> T:
        ...
```

具体接口细节由 Developer 根据 Python typing 合理实现。

核心原则：

```text
Gateway
知道 Provider Interface

Provider Adapter
知道具体 SDK

Agent Node
什么都不知道
```

---

# 10. Model routing configuration

建立显式配置结构。

例如：

```text
ModelRoute

profile
provider
model
```

概念上类似：

```yaml
cheap:
  provider: deepseek
  model: some-cheap-model

strong:
  provider: openai
  model: some-strong-model

fallback:
  provider: deepseek
  model: another-model
```

**本任务不写真实模型名称。**

测试中允许使用：

```text
mock-cheap
mock-strong
```

---

# 11. ModelGateway

实现：

```python
ModelGateway
```

职责严格限定为：

```text
收到 ModelRequest
      ↓
读取 profile
      ↓
获得 ModelRoute
      ↓
找到 Provider
      ↓
执行 Provider
      ↓
返回统一结果
```

Gateway 可以负责：

* profile routing；
* provider lookup；
* missing route validation；
* missing provider validation；
* structured output validation；
  -统一错误包装。

Gateway 不负责：

* Prompt构建；
* Intent判断；
* Action判断；
* Tool选择；
  -业务 fallback；
  -修改 OpsAgentState；
* LangGraph routing。

---

# 12. Error hierarchy

建立明确异常体系。

至少考虑：

```text
ModelGatewayError

ModelRouteNotFoundError

ModelProviderNotFoundError

ModelInvocationError

ModelStructuredOutputError
```

具体命名可以微调。

要求：

调用方能够区分：

```text
配置错误
Provider调用错误
Structured Output错误
```

不得只抛：

```python
Exception("model failed")
```

---

# 13. MockModelProvider

本任务必须实现一个真正可用于后续 Agent Test 的：

```python
MockModelProvider
```

它不能只：

```python
return "hello"
```

应至少支持：

### Queue / predefined response

测试代码可以准备：

```text
Response 1
Response 2
Response 3
```

然后依次消费。

### Structured output

能够返回：

```python
response_model(...)
```

或从预定义 payload 进行 Pydantic validation。

### Invocation history

必须可以检查：

```text
调用次数
收到的 ModelRequest
使用的 model
task
profile
```

这样未来可以测试：

> understand_request 是否真的调用了 cheap profile。

而不是连接真实 DeepSeek。

---

# 14. Async-first

Gateway 和 Provider Contract 从第一版采用：

```python
async
```

原因：

后续 Agent Runtime、FastAPI、LLM API 和 Tool Execution 都是典型 I/O workload。

不要第一版做同步接口、下一阶段再整体改 async。

---

# 15. Architecture constraints

必须遵守现有：

```text
Model = business brain
Code = deterministic harness
```

本任务虽然开发 Model infrastructure，但：

## 禁止业务判断

不得出现：

```python
if intent == ...
if request_type == ...
if user_query contains ...
```

---

## 禁止真实 Provider

不得：

```text
读取 DEEPSEEK_API_KEY
读取 OPENAI_API_KEY
调用互联网模型
```

真实 Provider 在后续独立 Task 实现。

---

## 禁止 LangGraph

不得新增：

```text
StateGraph
Node
Edge
Checkpoint
Router
```

---

## 禁止业务 Prompt

不得实现：

```text
Intent Prompt
Decision Prompt
Tool Prompt
Reply Prompt
```

---

## 禁止修改 OpsAgentState

本任务原则上不得修改：

```text
src/opsmind/state.py
```

如果 Developer 认为 Model Gateway 必须修改公共 State Contract：

停止实施该部分，并标记：

```text
needs:architecture
PM Action: DECISION_REQUIRED
```

---

# 16. Testing requirements — Developer

至少测试：

### Profile routing

```text
CHEAP → configured cheap route
STRONG → configured strong route
```

---

### Missing route

不存在配置：

```text
ModelRouteNotFoundError
```

---

### Missing provider

Route存在但Provider没有注册：

必须失败。

---

### Text invocation

验证：

```text
request
→ gateway
→ mock provider
→ ModelResponse
```

---

### Structured invocation

定义测试 Pydantic Model：

```python
class ExampleOutput(BaseModel):
    answer: str
    confidence: float
```

验证成功解析。

---

### Invalid structured output

Mock 返回非法 payload：

必须：

```text
ModelStructuredOutputError
```

或等价明确异常。

---

### Invocation history

验证 Mock Provider 确实记录：

```text
profile
task
messages
model
```

---

### Async behavior

所有主要 API 必须可通过 async test 正常使用。

---

# 17. Independent Tester responsibilities

Tester不能只重复 Developer Test。

重点主动测试：

* empty messages；
* invalid profile configuration；
* duplicate provider registration；
* malformed structured payload；
* unexpected additional structured fields；
* Provider exception；
* non-finite latency/token metadata；
* negative token usage；
* request metadata JSON boundary；
* Mock response queue exhausted；
  -并行调用是否发生明显共享状态污染。

Tester发现 Contract 设计问题时：

```text
MAJOR / BLOCKER
```

不能为了让测试通过直接绕开 Gateway。

---

# 18. Reviewer focus

Reviewer必须特别检查：

### 1. Provider leakage

确认 `deepseek`、`openai` 等具体 SDK 没有进入 Agent公共层。

### 2. Business logic leakage

确认 Gateway没有变成新的 Business Router。

### 3. Over-engineering

拒绝：

```text
十几层 Factory
Plugin framework
动态反射系统
复杂 dependency injection container
```

当前只需要一个简单、清晰、typed Gateway。

### 4. Structured output

确认不是：

```python
dict[str, Any]
```

一路传递。

应该真正经过 Pydantic validation。

### 5. Testability

后续 Agent Node 必须能够完全通过 Mock Provider进行单元测试。

---

# 19. Required documentation update

新增：

```text
docs/MODEL_GATEWAY.md
```

只写稳定 Contract：

```text
为什么有Gateway
Profile是什么
Provider是什么
Node如何调用
Structured Output怎么工作
错误边界
未来如何接DeepSeek
```

不要写开发过程流水账。

如果实际设计与 `ARCHITECTURE.md` 冲突，不能直接修改架构文档掩盖冲突。

应触发 PM Review。

---

# 20. Acceptance criteria

全部满足才可 DONE：

* [ ] ModelProfile 已定义
* [ ] ModelTask 已定义
* [ ] ModelMessage 已定义
* [ ] ModelRequest 已定义
* [ ] ModelResponse / ModelUsage 已定义
* [ ] ModelProvider abstraction 已建立
* [ ] ModelRoute configuration 已建立
* [ ] ModelGateway 已实现
* [ ] text invocation 可运行
* [ ] structured invocation 可运行
* [ ] MockModelProvider 已实现
* [ ] Mock invocation history 可检查
* [ ] 明确 error hierarchy
* [ ] API 为 async-first
* [ ] 未接真实 DeepSeek/OpenAI API
* [ ] 未实现 LangGraph
* [ ] 未实现业务 Prompt
* [ ] 未修改 Agent业务逻辑
* [ ] 未削弱现有 State validation
* [ ] Developer tests PASS
* [ ] Independent Tester PASS
* [ ] Reviewer APPROVE
* [ ] Ruff PASS
* [ ] mypy PASS
* [ ] uv lock check PASS
* [ ] Delivery Reporter 已更新 GitHub

---

# 21. Architecture impact

预期：

```text
CROSS_MODULE
```

原因：

后续所有 Model-driven Node 都会依赖 Model Gateway Contract。

如果 Developer认为需要改变：

```text
ARCHITECTURE_CHANGE
```

则必须先提交 ADR / PM Architecture Gate，不得自行合并。

---

# 22. Delivery workflow

```text
Issue
 ↓
Developer — Luna Max
 ↓
Delivery Reporter
 ↓
Independent Tester — Luna Max
 ↓
Delivery Reporter
 ↓
Reviewer — Luna Max
 ↓
Delivery Reporter
 ↓
READY_TO_MERGE
```

如果出现：

```text
同一实现失败两次
Gateway Contract需要重构
typing无法合理表达Structured Output
Provider边界与架构冲突
```

升级：

```text
Escalation Architect / Sol
```

不要无限循环尝试。

---

# 23. Completion report

Delivery Reporter最终必须告诉 PM：

```text
Task
PR
Commit
Files changed

Gateway API
Provider API
Supported profiles

Unit tests
Tester result
Reviewer result
CI result

Architecture impact
Deviations
Blockers
PM action
```

不要粘贴完整测试日志。
