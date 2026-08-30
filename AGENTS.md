# OpsMind — Agent Repository Guide

## 1. Repository purpose

OpsMind is an educational but production-shaped manufacturing IT operations Agent platform.

The first product is a single intelligent operations Agent that handles common enterprise IT support cases in a fully synthetic manufacturing environment.

The project intentionally uses:
- synthetic users, permissions, work orders, incidents, logs and knowledge;
- production-like schemas, tool contracts, state management and observability;
- a model-first Agent architecture;
- deterministic code only where runtime execution, validation, persistence or hard safety boundaries require it.

Read these documents before changing architecture:
- `docs/PRODUCT.md`
- `docs/ARCHITECTURE.md`
- `docs/DEVELOPMENT.md`
- `docs/TASK_TEMPLATE.md`
- `docs/REPORTING.md`

---

## 2. Core engineering principles

### 2.1 Model-first business reasoning

Business decisions should be performed by models unless there is a strong runtime or safety reason not to.

Examples that SHOULD normally be model-driven:
- request understanding;
- intent classification;
- request type identification;
- risk-signal detection;
- next-action decision;
- tool selection;
- tool argument extraction;
- interpretation of tool results;
- decision whether additional evidence is required;
- clarification generation;
- final response generation;
- handoff summary generation.

Do NOT replace these decisions with expanding `if/elif` business rules simply because they are easier to implement.

### 2.2 Code is the harness, not the business brain

Deterministic code SHOULD handle:
- schema validation;
- actual tool execution;
- persistence and checkpoints;
- thread/session management;
- timeout and retry enforcement;
- maximum-loop enforcement;
- hard permission boundaries;
- allow/deny policy enforcement;
- idempotency;
- observability hooks;
- artifact storage;
- test fixtures.

### 2.3 Hard safety boundaries cannot rely only on prompts

A model may recommend an action, but the harness must independently block actions outside the Agent's permitted capabilities.

V0.1 is read-only.

No model output may bypass this rule.

### 2.4 State contains cognition, artifacts contain bulk evidence

Do not place large raw tool outputs directly into long-lived Agent state.

Example:

Bad:
- 5,000 raw log lines stored in state.

Good:
- raw logs stored in an artifact store;
- state contains an evidence summary, key fields, source metadata and artifact reference.

### 2.5 Tools are capabilities, not business branches

Do not write code such as:

```python
if intent == "WORKFLOW_ISSUE":
    use_work_order_tool()
```

The model should select the appropriate tool from the currently available tool contracts.

The harness validates and executes the selected tool.

### 2.6 Every Agent loop must converge

The runtime must enforce:
- maximum rounds;
- maximum tool calls;
- tool timeout;
- no uncontrolled recursive execution.

The action-decision model should also be instructed to stop acquiring information once enough evidence exists.

### 2.7 Eval precedes optimization

Do not optimize prompts, routing or model choice based only on anecdotal examples.

Changes to Agent behavior should be evaluated against the Golden Cases and regression datasets.

### 2.8 Architecture changes require an ADR

Create an ADR under `docs/adr/` when changing:
- Agent graph topology;
- state semantics;
- model-routing strategy;
- tool execution boundary;
- persistence architecture;
- safety architecture;
- multi-Agent topology;
- deployment architecture.

---

## 3. V0.1 scope

V0.1 covers these Golden Cases:

- C01: how to close a fault work order;
- C03: missing menu / access permission;
- C05: work order waiting in a normal approval node;
- C06: work order submission validation failure;
- C09: HTTP 500 while opening the system;
- C10: site-wide outage;
- C11: request to grant administrator permission;
- C12: continuation of a previously unresolved case.

Do not broaden product scope without an explicit task.

---

## 4. Development-agent roles

Development uses artifact-driven multi-Agent collaboration.

Roles:
- PM / Architect
- Developer
- Tester
- Reviewer
- Delivery Reporter
- Escalation Architect

Agents should communicate primarily through:
- task specifications;
- code changes;
- test reports;
- review reports;
- ADRs.

Avoid open-ended Agent-to-Agent conversation loops.

Read `docs/DEVELOPMENT.md` for details.

---

## 5. Task execution rules

Before implementing a task:

1. Read the task file.
2. Read only the linked architecture/product documents needed for that task.
3. Inspect existing code before proposing new abstractions.
4. Do not broaden scope.
5. Do not silently change architecture.
6. Add or update tests.
7. Run the required validation commands.
8. Report unresolved conflicts instead of guessing.

---

## 6. Definition of done

A development task is not complete until:
- acceptance criteria pass;
- relevant tests pass;
- no architecture constraint is violated;
- public schemas remain typed;
- documentation is updated when behavior changed;
- reviewer issues rated Blocker or Major are resolved.

---

## 7. Prohibited shortcuts

Do not:
- hardcode Golden Case answers;
- identify cases by exact user wording;
- bypass the model to make business decisions merely to pass tests;
- place secrets in the repository;
- couple Agent logic to one concrete LLM vendor;
- couple Agent logic directly to one database implementation;
- introduce a second Agent only to make the system appear "multi-Agent";
- add Kubernetes, MCP, A2A or other infrastructure without a task requiring it.

---

## 8. Model configuration

Model names must be configurable.

Code should target logical model profiles such as:
- `cheap`
- `strong`
- `fallback`

The concrete provider/model is supplied by configuration.

The expected initial product configuration is:
- cheap profile: cost-efficient DeepSeek model;
- strong profile: stronger model used only when eval data justifies escalation.

Never scatter concrete model names through Agent nodes.

---

## 9. Repository philosophy

The repository should stay understandable to a new engineering Agent.

Prefer:
- small modules;
- explicit contracts;
- typed schemas;
- narrow tasks;
- visible state transitions;
- testable nodes;
- documented architecture decisions.

Avoid:
- giant prompts;
- giant state objects containing everything;
- opaque utility layers;
- unnecessary abstractions;
- implicit business rules hidden in code.

## 10. GitHub reporting

GitHub Issues and Pull Requests are the development control plane. Read `docs/REPORTING.md`. Coding-session transcripts are not authoritative project state. The Delivery Reporter normalizes task state and validation evidence for PM consumption.
