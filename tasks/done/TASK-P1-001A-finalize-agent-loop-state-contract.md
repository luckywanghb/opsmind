# TASK-P1-001A — Finalize Agent Loop State Contract

## Status

DONE

## Risk

MEDIUM

## Objective

在开始 Model Gateway 和 LangGraph Runtime 开发之前，对当前 `OpsAgentState` 做最后一次小范围语义收口，使其能够准确支持后续 Model-first Agent Loop。

本任务只调整 State Contract，不实现模型、不实现 LangGraph、不实现 Tool。

---

## Background

当前 `OpsAgentState` 已经完成并通过完整测试。

现有架构确定：

```text
Request Understanding Model
        ↓
Action Decision Model
        ↓
ASK / SEARCH / REPLY / TRANSFER / END
```

Action Decision 不仅需要输出：

```text
action
reason
```

还需要明确：

```text
goal
```

即：

> 当前这一步动作准备解决什么问题。

例如：

```json
{
  "action": "SEARCH",
  "goal": "确认工单 WO20260001 当前处于哪个流程节点，以及是否存在异常流转",
  "rationale": "当前已有工单编号，但缺少实时流程状态"
}
```

`goal` 将作为后续 Tool Selection Model 的重要输入。

---

# 1. Required changes

## 1.1 Extend DecisionState

当前：

```python
class DecisionState:
    action
    rationale
```

修改为：

```python
class DecisionState:
    action
    goal
    rationale
```

语义要求：

### action

模型选择的下一步动作。

允许：

```text
ASK_USER
SEARCH
REPLY
TRANSFER_HUMAN
END_CONVERSATION
```

### goal

描述：

> 当前 Action 希望解决的具体问题或取得的具体信息。

例如：

```text
确认用户缺少哪个菜单权限
```

而不是：

```text
解决用户问题
```

要求保持 compact。

### rationale

描述：

> 为什么当前应该执行这个 Action。

例如：

```text
用户已经提供工单号，但当前缺少实时流程状态。
```

---

## 1.2 Introduce TaskStatus

目前 `TaskState.status` 是普通字符串。

增加：

```python
class TaskStatus(StrEnum)
```

建议值：

```text
ACTIVE
WAITING_USER
INVESTIGATING
READY_TO_REPLY
TRANSFERRED
RESOLVED
CLOSED
```

语义：

### ACTIVE

任务已经建立，正在处理。

### WAITING_USER

Agent 已经 ASK_USER，等待用户补充信息。

### INVESTIGATING

正在进行查询、诊断或证据获取。

### READY_TO_REPLY

已有足够证据，可以形成回复。

### TRANSFERRED

已转交人工。

### RESOLVED

问题已经确认解决。

### CLOSED

会话/任务已经正式结束。

---

## 1.3 Introduce ResolutionStatus

目前：

```text
ConversationState.previous_resolution_status
```

是普通字符串。

增加：

```python
class ResolutionStatus(StrEnum)
```

建议：

```text
UNKNOWN
UNRESOLVED
PARTIALLY_RESOLVED
RESOLVED
```

用于描述：

> 当前问题是否已经解决。

注意：

```text
TaskStatus
```

和：

```text
ResolutionStatus
```

不能混为一个概念。

例如：

```text
TaskStatus = WAITING_USER
ResolutionStatus = UNRESOLVED
```

是合法组合。

---

# 2. Architecture constraints

必须遵守：

### Model-first

不要因为增加这些 Enum 而添加任何：

```python
if intent == ...
```

或：

```python
if request_type == ...
```

业务路由。

这些字段只是 State Contract。

---

### No Graph

本任务不得实现：

```text
LangGraph
Nodes
Edges
Router
Checkpoint
```

---

### No Model integration

不得添加：

```text
DeepSeek
OpenAI
Anthropic
LangChain ChatModel
```

等任何模型 Client。

---

### No Tools

不得实现：

```text
knowledge_search
work_order_query
permission_query
log_search
incident_query
```

---

### Preserve current validation

不得削弱当前已经存在的：

```text
extra="forbid"
strict numeric validation
JSON finite-number validation
Evidence size budget
Evidence mutation-boundary revalidation
READ_ONLY safety default
```

---

# 3. Tests

Developer 必须更新或新增测试。

至少覆盖：

## DecisionState

```text
action + goal + rationale
```

正常构造。

并验证：

```text
goal
```

不存在类型错误。

---

## TaskStatus

测试所有 Enum 值。

非法值必须被 Pydantic 拒绝。

---

## ResolutionStatus

测试所有 Enum 值。

非法值必须被拒绝。

---

## JSON round trip

构造一个完整：

```text
OpsAgentState
```

包含：

```text
DecisionState.goal
TaskStatus
ResolutionStatus
```

执行：

```python
model_dump_json()
model_validate_json()
```

结果必须一致。

---

## Regression

现有所有 State Tests 必须继续通过。

---

# 4. Validation commands

执行：

```bash
uv run pytest
uv run ruff check .
uv run mypy src
uv lock --check
```

全部必须 PASS。

---

# 5. Developer workflow

Developer 使用 Luna Max 或当前配置的 efficient coding profile。

Developer：

1. 阅读：

   * `AGENTS.md`
   * `docs/ARCHITECTURE.md`
   * `docs/PHASE1_PLAN.md`
   * 当前 `src/opsmind/state.py`
   * TASK-001 完成记录

2. 实现本 Task。

3. 编写 Developer tests。

4. 执行全部 validation。

5. 创建 PR。

---

# 6. Tester

Developer 完成后，由独立 Tester Agent 阅读：

```text
Task Spec
+
State implementation
```

重点检查：

* Enum 是否准确；
* TaskStatus 和 ResolutionStatus 是否混淆；
* JSON serialization；
* invalid enum；
* mutable state；
* 原有 Evidence boundary 是否受到影响；
* 是否偷偷添加业务判断。

Tester 不应仅运行 Developer 已有测试。

Tester应该增加至少一组独立边界测试。

---

# 7. Reviewer

Reviewer 重点检查：

### Architecture

是否仍然满足：

```text
Model = business brain
Code = deterministic harness
```

### State semantics

重点检查：

```text
TaskStatus
ResolutionStatus
Decision goal
```

三者是否语义清楚且没有重复职责。

### Scope

不得出现：

```text
Model Gateway
LangGraph
Tool
Business Routing
```

---

# 8. Delivery Reporter

Tester / Reviewer 完成后调用：

```text
Delivery Reporter
```

更新 GitHub：

```text
Issue
PR
Validation
Review
Architecture impact
PM action
```

该任务正常应标记：

```text
Architecture impact:
CROSS_MODULE
```

原因：

DecisionState / TaskState / ConversationState 是未来多个 Agent Node 都会消费的公共 Contract。

---

# 9. Acceptance criteria

全部满足后才可 DONE：

* [x] `DecisionState` 增加 `goal`
* [x] 增加 `TaskStatus`
* [x] 增加 `ResolutionStatus`
* [x] `TaskState.status` 使用 `TaskStatus`
* [x] `ConversationState.previous_resolution_status` 使用 `ResolutionStatus`
* [x] 公共 export 已更新
* [x] JSON round trip 正常
* [x] invalid Enum 测试正常
* [x] 原 State regression tests 全部通过
* [x] Ruff PASS
* [x] mypy PASS
* [x] lock check PASS
* [x] Tester PASS
* [x] Reviewer APPROVE
* [x] Delivery Reporter 更新 GitHub 状态
* [x] 没有实现任何 Model / Graph / Tool

---

# 10. Escalation rule

如果 Developer 认为：

```text
TaskStatus
```

或：

```text
ResolutionStatus
```

的枚举设计无法支持后续 LangGraph 生命周期，

**不要自行重新设计。**

在 GitHub Task 中标记：

```text
needs:pm-decision
```

并由 Delivery Reporter 输出：

```text
PM Action:
DECISION_REQUIRED
```

说明：

1. 当前问题；
2. 为什么现有定义不足；
3. 建议方案 A；
4. 建议方案 B；
5. 各自影响。

等待 PM / Architect 决策。

---

# 11. Completion reports

## Developer

- Added `DecisionState.goal`.
- Added and exported `TaskStatus` and `ResolutionStatus`.
- Replaced the two untyped status strings with their corresponding enums.
- Added Developer tests for enum values, invalid values and JSON round trip.
- Validation: 70 tests passed; Ruff, mypy and lock check passed.

## Tester

```text
PASS
```

- Added independent lifecycle, assignment, goal-type and Evidence regression
  boundaries.
- Final validation: 88 tests passed; Ruff, mypy and lock check passed.
- Production defects found: none.

## Reviewer

```text
APPROVE
```

- BLOCKER: none.
- MAJOR: none.
- MINOR: none.
- NIT: `DecisionState.goal` has no enforced length limit. The task defines no
  numeric threshold and `rationale` is likewise unconstrained, so this does not
  block approval.

## Delivery Reporter

- GitHub Issue: `#3`
- GitHub Pull Request: `#4`
- Stage before merge: `READY_TO_MERGE`
- Architecture impact: `CROSS_MODULE`
- PM action: `NONE`
- GitHub cannot formally approve a PR authored by the same account; PR review
  `5060107327` records the independent Agent's APPROVE verdict.
