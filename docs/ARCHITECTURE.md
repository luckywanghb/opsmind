# OpsMind Architecture — V0.1

Status: TASK-P1-006 proposal — PM architecture gate required
Architecture style: Model-first Agent + deterministic harness  
Primary Agent runtime: LangGraph  
Business environment: Fully synthetic manufacturing IT environment

---

# 1. Architectural objective

OpsMind should behave like a real enterprise operations Agent while remaining safe to publish and demonstrate.

The system should demonstrate:
- stateful Agent execution;
- multi-step reasoning;
- structured tool calling;
- evidence-driven answers;
- context continuity;
- loop convergence;
- operational observability;
- hard safety boundaries;
- future extensibility toward action-taking and multi-Agent workflows.

The system does not attempt to reproduce a real company's internal systems.

Instead, it implements stable contracts around synthetic enterprise services.

---

# 2. System overview

```text
User
 │
 ▼
Web / Agent Client
 │
 ▼
Agent Runtime
 │
 ├─ Context Assembly
 │
 ├─ Request Understanding Model
 │
 ├─ Action Decision Model
 │
 ├─ Action Execution
 │    ├─ ASK_USER
 │    ├─ SEARCH
 │    ├─ REPLY
 │    ├─ TRANSFER_HUMAN
 │    └─ END_CONVERSATION
 │
 ├─ Tool Selection Model
 │
 ├─ Tool Execution Harness
 │
 ├─ Tool Result Review Model
 │
 └─ State / Evidence Update
 │
 ▼
Persistence / Observability
```

---

# 3. Architectural boundary: model vs code

## 3.1 Model-controlled responsibilities

The model normally decides:

### Request understanding
- primary intent;
- request type;
- symptom;
- extracted entities;
- risk signal;
- uncertainty.

### Action decision
One of:
- ASK_USER;
- SEARCH;
- REPLY;
- TRANSFER_HUMAN;
- END_CONVERSATION.

### Search planning
When action = SEARCH:
- which available tool should be called;
- what arguments should be supplied;
- what information the call is expected to resolve.

### Result interpretation
After a tool call:
- what evidence was established;
- which unresolved questions were resolved;
- what remains unknown;
- whether current evidence is sufficient.

### User-facing language
- clarification question;
- final answer;
- handoff summary.

## 3.2 Harness-controlled responsibilities

Code handles:
- schema validation;
- execution of selected tools;
- tool allow-listing;
- runtime permissions;
- checkpointing;
- state persistence;
- thread identity;
- timeout;
- retry;
- maximum rounds;
- maximum tool calls;
- raw artifact storage;
- telemetry;
- deterministic safety blocks.

The code harness must not become a hidden business decision engine.

---

# 4. Agent loop

```text
START
  │
  ▼
assemble_context
  │
  ▼
understand_request [MODEL]
  │
  ▼
decide_action [MODEL]
  │
  ├── ASK_USER
  │     ▼
  │   compose_clarification [MODEL]
  │     ▼
  │    END
  │
  ├── SEARCH
  │     ▼
  │   select_tool [MODEL]
  │     ▼
  │   validate_tool_request [CODE]
  │     ▼
  │   enforce_tool_policy [CODE]
  │     ▼
  │   execute_tool [CODE]
  │     ▼
  │   review_tool_result [MODEL]
  │     ▼
  │   persist_artifact_and_evidence [CODE]
  │     └───────────────► decide_action
  │
  ├── REPLY
  │     ▼
  │   compose_reply [MODEL]
  │     ▼
  │   output_validation [CODE]
  │     ▼
  │    END
  │
  ├── TRANSFER_HUMAN
  │     ▼
  │   build_handoff [MODEL]
  │     ▼
  │    END
  │
  └── END_CONVERSATION
        ▼
      close_case [CODE]
        ▼
       END
```

Important:
- ASK_USER ends the current run.
- The next user message resumes the same thread.
- LangGraph `interrupt()` is reserved for future real human approval of a suspended execution, not ordinary clarification.

---

# 5. V0.1 understanding taxonomy

## 5.1 Primary intent

- SYSTEM_OPERATION
- BUSINESS_RULE
- ACCESS_ISSUE
- WORKFLOW_ISSUE
- DATA_ISSUE
- OTHER

Primary intent describes the business domain of the user's problem.

## 5.2 Request type

- HOW_TO
- EXPLAIN
- DIAGNOSE
- CHECK_STATUS
- EXECUTE_CHANGE
- CONTINUE_CASE
- CONFIRM_RESOLVED
- OTHER

Request type describes what the user wants the Agent to do.

## 5.3 Risk signal

- NONE
- PRIVILEGED_CHANGE
- BROAD_OUTAGE
- SECURITY_SUSPECTED
- DESTRUCTIVE_OPERATION

Risk signal is model-produced advisory metadata.

It does not replace deterministic runtime policy.

---

# 6. State model

Logical state:

```text
OpsAgentState

identity
conversation
understanding
task
loop
facts
evidence
decision
tool
safety
handoff
response
```

## 6.1 Identity

Contains:
- user_id;
- site_id;
- department;
- roles;
- source context.

## 6.2 Conversation

Contains:
- thread_id;
- original query;
- current query;
- compact history / summary;
- previous resolution status.

## 6.3 Understanding

Contains structured output from request-understanding model.

## 6.4 Facts

Contains:
- confirmed facts;
- unresolved questions.

Facts should be compact and task-relevant.

## 6.5 Evidence

Each evidence item should contain at minimum:
- source;
- summary;
- key fields;
- artifact reference when applicable;
- timestamp.

## 6.6 Tool state

Contains only current/most relevant tool-planning state.

Do not persist entire raw results here.

---

# 7. Artifact strategy

Large tool outputs are stored outside the reasoning state.

Examples:
- log result sets;
- long RAG passages;
- large JSON responses;
- screenshots;
- diagnostic dumps.

Flow:

```text
Tool raw result
   ├─► Artifact Store
   └─► Result Review Model
          ↓
       Evidence
          ↓
       Agent State
```

This reduces context growth and allows later evidence inspection.

---

# 8. Tool architecture

TASK-P1-006 implements only these synthetic V0.1 read-only capabilities:

- `work_order_query`
- `permission_query`
- `incident_query`

`knowledge_search` and `log_search` remain future capabilities and are not
registered by this task.

Every tool has a typed contract:

```text
ToolSpec

id
name
description
capability
input_schema
output_schema
mode
risk_level
timeout
retry_policy
side_effect
```

V0.1 tools are READ-only.

The model chooses the tool.

The harness checks:
- requested tool exists;
- tool is allowed;
- arguments validate;
- call does not violate policy.

---

# 9. Synthetic enterprise

Company:
- Nova Manufacturing Group

System:
- EquipFlow

Sites:
- 星川基地
- 云岭基地
- 临海基地

Example services:
- IAM
- Workflow
- LogCenter
- OpsWiki
- Incident Center

Synthetic data may grow over time without changing Agent Kernel contracts.

Adapters should isolate the Agent from concrete storage.

Example:

```text
work_order_query
      │
      ▼
WorkOrderAdapter
      │
   ┌──┴────────┐
   ▼           ▼
Mock DB     Future real API
```

---

# 10. Model gateway

All model access goes through a Model Gateway.

Logical profiles:

```yaml
profiles:
  cheap:
    provider: configurable
    model: configurable

  strong:
    provider: configurable
    model: configurable

  fallback:
    provider: configurable
    model: configurable
```

Initial policy:
- use a low-cost DeepSeek profile for normal Agent nodes;
- do not use a stronger model unless eval results show a clear benefit;
- allow later node-specific routing based on measured error rates.

Nodes must request a logical profile rather than instantiate provider clients directly.

---

# 11. Loop controls

The harness must enforce:
- configurable `max_rounds`;
- configurable maximum tool calls;
- per-tool timeout;
- retry limits;
- no repeated identical successful tool call unless input/evidence materially changed.

The model should receive action history and current evidence so that it can reason about whether additional work is necessary.

The current in-memory graph enforces the limits in `LoopState`, takes the
minimum of the state and per-tool timeout, and rejects a repeated successful
tool signature within one run.  It does not persist checkpoints or resume a
thread.

The harness enforces limits; the model performs the business judgment.

---

# 12. Safety V0.1

V0.1 capability mode:

```text
READ_ONLY
```

Therefore a request such as:

> Grant U10023 administrator permission.

may be understood by the model as:

```text
ACCESS_ISSUE
EXECUTE_CHANGE
PRIVILEGED_CHANGE
```

but no write tool exists.

The decision model should normally choose TRANSFER_HUMAN.

Even if it incorrectly selects an execution path in a future extension, the tool policy layer must reject unauthorized write capabilities.

---

# 13. Golden Cases

The Agent Kernel is considered viable only when it reliably handles:

- C01 operation guidance;
- C03 missing permission;
- C05 normal work-order wait;
- C06 validation failure requiring clarification;
- C09 HTTP 500;
- C10 site-wide outage;
- C11 privileged change request;
- C12 continued unresolved conversation.

Do not hardcode these cases.  D01–D03 from Issue #16 and the existing Golden
Cases are eval fixtures, not runtime branches.  The model selects tools from
the registry for any supported input; unknown records are typed `not_found`.

---

# 14. Evaluation dimensions

At minimum:

- intent accuracy;
- request-type accuracy;
- entity extraction accuracy;
- next-action accuracy;
- clarification necessity;
- unnecessary clarification rate;
- tool-selection accuracy;
- argument extraction accuracy;
- unnecessary search rate;
- duplicate tool-call rate;
- loop convergence;
- grounded answer rate;
- handoff quality;
- latency;
- cost per resolved case.

---

# 15. Future architecture

Not part of V0.1:

### V0.2
- write actions;
- human approval;
- LangGraph interrupt/resume;
- approval console.

### Later
- additional Agent domains;
- Agent Registry;
- Agent-as-tool patterns;
- MCP for independently operated tool services;
- A2A only when process/team boundaries justify it.

Multi-Agent is not a product requirement by itself.

It should be introduced only when context isolation, ownership or independent deployment provides concrete value.
