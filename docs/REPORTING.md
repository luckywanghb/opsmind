# OpsMind GitHub Reporting & Project Control Plane

Status: Baseline  
Purpose: Make multi-Agent development legible to the PM/Architect without requiring session-by-session supervision.

---

# 1. Core principle

GitHub is the development control plane.

Do not treat coding-agent sessions as the source of truth.

The authoritative artifacts are:

| Artifact | Purpose | Authoritative for |
|---|---|---|
| GitHub Issue | Task definition and current task state | What should be done / current status |
| Pull Request | Implementation handoff | What changed and why |
| GitHub Actions checks | Machine validation | Build / test / eval status |
| PR Review | Independent quality verdict | Approve / request changes |
| ADR / architecture docs | Durable architectural decisions | Why architecture changed |

The PM should not need raw agent transcripts to understand project state.

---

# 2. Why this structure

For Agent-first development, the scarce resource is review attention.

Therefore:
- agents should produce structured artifacts;
- project state should be visible outside an individual session;
- reports should emphasize decisions, evidence and blockers;
- raw execution logs should be retained only when they help debug a failure.

Do not create a permanent repository document for every transient thought.

---

# 3. Task state machine

Use the following logical states:

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
  ├── BLOCKED ──────────► BLOCKED
  ├── ESCALATE ─────────► ESCALATION
  └── APPROVE ──────────► READY_TO_MERGE
                            ↓
                          MERGED
                            ↓
                           DONE
```

Recommended GitHub labels:

```text
status:backlog
status:ready
status:in-progress
status:test
status:review
status:blocked
status:ready-to-merge
status:done

risk:low
risk:medium
risk:high

agent:developer
agent:tester
agent:reviewer
agent:reporter

needs:pm-decision
needs:architecture
needs:escalation
```

A GitHub Project may provide a visual board later, but the Issue and linked PR remain the canonical records.

---

# 4. What the PM/Architect must always be able to see

The Reporter must maintain a compact PM View containing these fields.

## 4.1 Identity
- Task ID
- Issue number
- PR number, if any
- current branch
- latest commit SHA
- current stage
- current responsible role

## 4.2 Outcome
One to three bullets:
- what capability now exists;
- what behavior changed;
- whether the acceptance criteria are satisfied.

## 4.3 Validation evidence
Report machine evidence, not vague statements.

At minimum when applicable:
- unit tests: passed / failed / count;
- integration tests: passed / failed;
- Golden Case eval: passed / failed / metric delta;
- lint/type checks;
- CI workflow status;
- relevant artifact links.

Example:

```text
Unit tests: 48 passed, 0 failed
Golden cases: 8/8
Next-action accuracy: 87.5% → 93.8%
CI: PASS
```

## 4.4 Architecture impact
Choose one:

```text
NONE
LOCAL
CROSS_MODULE
ARCHITECTURE_CHANGE
```

If not NONE, summarize:
- state contract changes;
- graph changes;
- tool contract changes;
- model-routing changes;
- persistence/safety changes.

ARCHITECTURE_CHANGE requires an ADR and PM gate.

## 4.5 Deviations and decisions
Report only decisions that matter later.

Examples:
- task spec could not be implemented as written;
- a schema field was renamed;
- a library limitation changed implementation;
- a proposed abstraction was deliberately not added.

Do not report ordinary implementation choices.

## 4.6 Risks / blockers
Each blocker must say:

```text
Problem
Evidence
Impact
What has already been tried
Recommended next action
Who must decide
```

## 4.7 PM action required
Exactly one:

```text
NONE
REVIEW_REQUIRED
DECISION_REQUIRED
ESCALATION_REQUIRED
```

If a decision is required, formulate the decision as a short question with 2–3 options when possible.

---

# 5. What the PM normally does NOT need

Do not push these into the main status report unless debugging is required:
- full coding-agent transcript;
- every command executed;
- every file read;
- full compiler output when CI passed;
- full test logs when tests passed;
- raw model chain-of-thought;
- repetitive self-review notes;
- full raw tool output;
- ordinary implementation details with no architectural consequence.

Detailed logs belong in:
- GitHub Actions logs;
- workflow artifacts;
- PR diff;
- temporary cloud-agent logs.

---

# 6. GitHub Issue: canonical task record

Each task gets one Issue.

The Issue contains stable information:
- Goal
- Why
- Scope
- Non-goals
- Dependencies
- Risk
- Acceptance criteria
- Relevant architecture references

The Reporter maintains a small current-status section at the top or as a single maintained status comment.

Recommended status block:

```markdown
## Agent Status

- **Stage:** REVIEW
- **Owner:** reviewer
- **PR:** #42
- **Commit:** `abc1234`
- **Updated:** 2026-08-30T12:30:00+09:00
- **PM action:** NONE

### Current outcome
- Implemented typed Model Gateway.
- Provider-specific clients are isolated behind adapters.

### Validation
- Unit: 31 passed
- Integration: 7 passed
- CI: PASS

### Risk / blocker
None.
```

Prefer updating one status block instead of producing a long stream of repetitive comments.

Important discussion comments may remain separate when they contain a decision or review exchange.

---

# 7. Pull Request: implementation handoff

The PR is not the task specification.

It should answer:
1. What changed?
2. Why is this implementation correct?
3. What should a reviewer pay attention to?
4. What machine evidence exists?
5. Did architecture or contracts change?
6. What remains incomplete?

Every implementation PR should link its Issue.
Use a closing keyword when the PR fully completes that Issue, e.g. `Closes #18`.
Do not use a closing keyword for partial PRs.

---

# 8. GitHub Actions: machine-readable evidence

CI should report machine facts automatically.

Use status checks for:
- unit tests;
- integration tests;
- lint;
- type checks;
- Golden Case eval;
- security/basic dependency checks when introduced.

Use `GITHUB_STEP_SUMMARY` to show concise Markdown results on the workflow summary page.

Good summary:

```text
### OpsMind Validation

Unit tests: 48 passed
Integration tests: 12 passed
Golden cases: 8/8
Action accuracy: 93.8%
Tool selection accuracy: 100%
```

Do not require PM to open raw CI logs to know whether validation passed.

Upload detailed artifacts only where useful, e.g.:
- coverage reports;
- failed Golden Case traces;
- screenshots;
- benchmark JSON;
- large test reports.

---

# 9. PR review: independent verdict

Reviewer must use an actual PR review where possible.

Decision:

```text
APPROVE
REQUEST_CHANGES
COMMENT / ESCALATE
```

Findings:

```text
BLOCKER
MAJOR
MINOR
NIT
```

Reporter must not reinterpret a BLOCKER as a success.
The PM View should surface only unresolved BLOCKER/MAJOR findings by default.

---

# 10. Delivery Reporter Agent

The Reporter is a state-transition and reporting Agent.

Recommended model:
- Luna Max / efficient coding-reasoning profile.

It is invoked:
- when Developer declares implementation complete;
- after Tester completes;
- after Reviewer completes;
- immediately when a task becomes blocked;
- before a high-risk task requests PM approval.

For LOW-risk tasks, a single Reporter run at completion is sufficient unless blocked.

The Reporter reads:
- Issue / task specification;
- linked PR metadata and diff summary;
- developer completion note;
- test results;
- GitHub Actions status;
- reviewer decision and unresolved review threads;
- relevant ADR when architecture changed.

The Reporter produces:
- normalized status;
- compact PM View;
- updated PR body;
- updated Issue status/labels;
- explicit PM action required.

It must not become another implementation reviewer.

---

# 11. Reporter permissions

Reporter MAY:
- read repository/task docs;
- inspect PR diff;
- inspect checks/workflow results;
- inspect PR comments and review threads;
- update Issue task status;
- update labels;
- create or update the PR description;
- open a PR for an already prepared task branch if workflow requires;
- mark a draft PR ready for review when all required evidence exists;
- post a concise handoff comment;
- link PR and Issue.

Reporter MUST NOT:
- modify product code;
- silently change acceptance criteria;
- approve its own work as Reviewer;
- dismiss a failing test;
- hide an unresolved BLOCKER;
- merge HIGH-risk work;
- alter architecture;
- close a task when required checks/reviews failed.

---

# 12. Reporter state normalization

Reporter outputs a machine-readable summary in addition to Markdown.

Suggested schema:

```json
{
  "task_id": "TASK-P1-02",
  "stage": "REVIEW",
  "risk": "MEDIUM",
  "issue": 18,
  "pr": 42,
  "commit_sha": "abc1234",
  "outcome": [
    "Implemented Model Gateway",
    "Added provider-independent model profiles"
  ],
  "validation": {
    "unit": {"status": "pass", "passed": 31, "failed": 0},
    "integration": {"status": "pass", "passed": 7, "failed": 0},
    "golden_cases": null,
    "ci": "pass"
  },
  "architecture_impact": "LOCAL",
  "deviations": [],
  "blockers": [],
  "review": {
    "decision": "APPROVE",
    "blocker_count": 0,
    "major_count": 0
  },
  "pm_action": "NONE"
}
```

This JSON may be embedded in an HTML comment in the PR body or stored as a CI artifact if later automation needs it.
Human-readable Markdown remains required.

---

# 13. When the PM should inspect the actual diff

The Reporter summary is enough for routine tracking.

The PM / Architect should inspect the diff directly when:
- risk = HIGH;
- architecture impact = ARCHITECTURE_CHANGE;
- state schema semantics changed;
- Agent graph topology changed;
- safety or tool permission logic changed;
- model-routing policy changed;
- Reviewer returns ESCALATE;
- repeated regression appears;
- tests pass but observed product behavior is suspicious.

For routine LOW/MEDIUM implementation, PM can rely primarily on Reporter + Reviewer + CI unless something is flagged.

---

# 14. Information retention rule

Transient state:
- stays in Issue/PR/Actions.

Durable knowledge:
- moves into repository docs.

Promote information into durable docs only when it changes:
- architecture;
- product contract;
- development rule;
- operational procedure;
- known long-lived limitation.

This prevents the repository from becoming a task-log archive.

---

# 15. PM visibility through GitHub

Once the repository is connected, the PM can inspect:
- current Issues and their state;
- PR metadata and diffs;
- PR comments and review submissions;
- unresolved review threads;
- workflow/check runs associated with commits.

Therefore the reporting format should optimize these GitHub surfaces rather than proprietary Agent-session logs.

This is pull-based visibility: the PM can retrieve current state whenever managing the project.
It is not equivalent to continuously watching Agent sessions in the background.
