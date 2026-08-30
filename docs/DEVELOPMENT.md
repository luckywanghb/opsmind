# OpsMind Agent-First Development Workflow

Status: Baseline

This repository is developed using an artifact-driven multi-Agent workflow.

The goal is not to maximize the number of Agents.

The goal is to reduce cost while obtaining independent implementation, testing and review.

---

# 1. Roles

## 1.1 PM / Architect

Recommended profile:
- strongest generally available reasoning model needed for architecture and product decisions.

Responsibilities:
- define product scope;
- maintain architecture;
- create task DAG;
- write acceptance criteria;
- identify dependencies;
- resolve ambiguous product decisions;
- approve architecture changes;
- evaluate phase gates;
- escalate issues to the human owner when a product choice is required.

The PM / Architect should not become the default code implementer.

---

## 1.2 Developer

Recommended profile:
- cost-efficient coding model with high effort when needed.

Responsibilities:
- implement a narrowly scoped task;
- inspect existing code before writing;
- follow architecture constraints;
- add implementation-level tests;
- run required validation;
- report deviations or blocked assumptions.

Developer may fix its own implementation/test failures.

Developer should not silently change task scope.

---

## 1.3 Tester

Recommended profile:
- cost-efficient coding model;
- separate context from Developer where practical.

Responsibilities:
- read task specification and acceptance criteria independently;
- inspect implementation;
- create adversarial and boundary tests;
- test failure handling;
- test state transitions;
- test model-output schema failures;
- identify missing regression coverage.

Tester should not merely run Developer-authored tests.

Tester may create test-only commits/changes where the task workflow permits.

---

## 1.4 Reviewer

Recommended profile:
- cost-efficient coding/reasoning model.

Default behavior:
- read-only review first.

Responsibilities:
- compare implementation against task specification;
- check architectural conformance;
- inspect tests and coverage;
- identify over-engineering;
- identify hidden hardcoded business logic;
- identify state pollution;
- identify safety regressions;
- identify undocumented behavior.

Review result must be one of:

```text
APPROVE
REQUEST_CHANGES
ESCALATE
```

Reviewer findings should be categorized:

```text
BLOCKER
MAJOR
MINOR
NIT
```

Only BLOCKER and MAJOR findings block completion.

---

## 1.5 Escalation Architect

Recommended profile:
- strongest reasoning model / advanced Sol-class model.

Use only when escalation conditions are met.

Responsibilities:
- root-cause difficult failures;
- resolve architecture conflicts;
- decide between materially different technical designs;
- handle repeated failed implementation attempts;
- resolve unclear LangGraph/runtime behavior;
- perform high-risk architecture review.

The Escalation Architect should return a concrete decision or remediation plan to the normal workflow.

---

# 2. Task risk levels

## LOW

Examples:
- documentation;
- enum/schema additions that do not alter semantics;
- mock-data additions;
- formatting;
- simple isolated utility.

Workflow:

```text
PM Task
  ↓
Developer
  ↓
automated tests
  ↓
Done
```

Reviewer optional.

---

## MEDIUM

Examples:
- new tool;
- new Agent node;
- state-field behavior;
- API endpoint;
- data adapter;
- prompt implementation;
- evaluator.

Workflow:

```text
PM Task
  ↓
Developer
  ↓
Tester
  ↓
Reviewer
  ↓
Done / Changes
```

---

## HIGH

Examples:
- graph topology;
- state architecture;
- context-compaction strategy;
- model-routing policy;
- tool-policy system;
- safety architecture;
- persistence model;
- deployment model;
- multi-Agent design.

Workflow:

```text
PM / Architect
  ↓
Developer
  ↓
Tester
  ↓
Reviewer
  ↓
PM Architecture Gate
  ↓
Done
```

An ADR is normally required.

---

# 3. Escalation triggers

Escalate to the stronger model when any applies:

- Developer fails to complete the same technical objective twice;
- two review cycles still contain the same BLOCKER;
- implementation requires changing architecture;
- runtime behavior contradicts documented framework behavior;
- tests expose a systemic state-management problem;
- design requires a non-obvious safety tradeoff;
- two plausible architectures have materially different future cost;
- PM cannot resolve a technical uncertainty with normal research.

Do not escalate simply because a task is large.

Split large tasks first.

---

# 4. Artifact-driven collaboration

Agents should not coordinate through unlimited free-form conversation.

The control plane is the task artifact.

A task contains:
- goal;
- non-goals;
- relevant docs;
- input/output contracts;
- acceptance criteria;
- risk;
- dependencies;
- validation commands.

Developer produces:
- implementation;
- implementation notes;
- test result.

Tester produces:
- additional tests;
- test report.

Reviewer produces:
- review report.

Architecture changes produce:
- ADR.

---

# 5. Task lifecycle

```text
BACKLOG
  ↓
READY
  ↓
IN_PROGRESS
  ↓
TEST
  ↓
REVIEW
  ├── REQUEST_CHANGES ──► IN_PROGRESS
  ├── ESCALATE ─────────► ESCALATION
  └── APPROVE ──────────► DONE
```

Task directories:

```text
tasks/
├── backlog/
├── active/
├── review/
└── done/
```

---

# 6. Parallel execution

Tasks may run in parallel only when their dependencies allow it.

Example:

```text
T001 State schemas ─────┐
                       ├─► T004 Agent graph
T002 Model gateway ─────┘

T003 Synthetic data ─────► T005 Tool adapters
```

T001, T002 and T003 may run concurrently.

T004 cannot begin before T001 and T002 satisfy their contracts.

Prefer parallelizing independent tasks rather than assigning multiple Agents to edit the same files.

---

# 7. Workspace isolation

When supported, each development task should operate in an isolated workspace / branch.

Preferred pattern:

```text
task/TASK-ID-dev
task/TASK-ID-test
```

Avoid concurrent Agents modifying the same files without an explicit integration task.

Git is the source of truth.

Cloud coding environments are replaceable execution environments.

---

# 8. Model-cost strategy

Use the cheapest model that reliably completes the role.

Suggested logical profiles:

```text
pm_architect       = strong
developer          = efficient-coding
tester             = efficient-coding
reviewer           = efficient-coding
escalation         = strongest
```

"Max" or highest reasoning effort should be used selectively for:
- difficult implementation;
- complex tests;
- architecture review;
- persistent bugs.

Do not use the most expensive profile automatically.

---

# 9. Development feedback loop

For Agent behavior tasks, implementation is incomplete without eval.

Preferred loop:

```text
Task spec
 ↓
Implementation
 ↓
Unit/integration tests
 ↓
Golden-case eval
 ↓
Bad cases
 ↓
Prompt / contract refinement
 ↓
Regression eval
```

Do not fix individual Golden Cases through exact-string logic.

---

# 10. Review checklist

Reviewer should explicitly inspect:

## Scope
- Did implementation satisfy the task and only the task?

## Architecture
- Is business reasoning model-driven where intended?
- Was deterministic logic introduced unnecessarily?
- Is Model Gateway used instead of direct vendor coupling?

## State
- Is state compact?
- Are raw results leaking into persistent state?
- Remember that in-place mutation inside a list or dictionary does not trigger
  Pydantic assignment validation. Before state crosses an Agent-node,
  checkpoint, or persistence boundary, call
  `OpsAgentState.model_validate(state)` and use the returned validated state.
- Are fields semantically clear?

## Tools
- Does the model select tools?
- Are arguments typed?
- Does harness validate before execution?
- Are timeouts and errors handled?

## Safety
- Can model output bypass read-only boundaries?
- Are secrets exposed?
- Are unsafe write capabilities introduced?

## Tests
- Are happy path, failure path and boundary conditions covered?
- Are schema-invalid model outputs tested?
- Are loops bounded?

## Maintainability
- Is new abstraction actually necessary?
- Are docs updated?

---

# 11. Human-owner decisions

The PM / Architect must ask the human project owner when a decision materially changes:
- product behavior;
- user experience;
- what data the simulated enterprise contains;
- whether the Agent may execute a class of write operation;
- acceptable cost/latency tradeoff;
- public-demo privacy;
- platform scope.

Pure implementation choices should normally be resolved without interrupting the owner.

---

# 12. Phase gates

## Phase 0 — Repository Harness
Complete when:
- AGENTS.md exists;
- architecture baseline exists;
- development workflow exists;
- task template exists.

## Phase 1 — Agent Kernel
Complete when:
- typed state exists;
- model gateway exists;
- graph skeleton runs;
- model-driven request understanding and action decision work;
- checkpoint/thread behavior is tested.

## Phase 2 — Tool System
Complete when:
- tool registry works;
- model selects tools;
- argument validation works;
- mock adapters work;
- result-review model converts results to evidence.

## Phase 3 — Synthetic Enterprise
Complete when:
- synthetic data exists for all Golden Cases;
- ground truth is deterministic;
- adapters expose stable contracts.

## Phase 4 — Golden Cases
Complete when:
- eight Golden Cases run as automated evals;
- regression metrics are recorded;
- critical bad cases are understood.

## Phase 5+
Proceed only after earlier gates are stable.

---

# 13. GitHub synchronization

After every completed development task:

1. record the final Developer, Tester and Reviewer status in the task artifact;
2. run the task's validation commands against the exact source to be committed;
3. commit the implementation, tests, documentation and completed task artifact;
4. push the commit to the configured GitHub repository;
5. verify that the remote branch points to the local commit;
6. include the commit identifier and remote synchronization result in the
   user-facing completion report.

Do not commit secrets, local environments, caches or raw enterprise artifacts.
If synchronization is unavailable, preserve the local commit and report the
remote failure rather than representing the task as uploaded.
