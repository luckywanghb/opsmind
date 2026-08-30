# OpsMind Phase 1 — Agent Kernel Plan

Status: IN_PROGRESS

## Objective

Build the smallest runnable Agent Kernel that preserves the V0.1 architecture:
typed state, provider-neutral model access, a bounded LangGraph loop, and tested
thread/checkpoint behavior.

## Task DAG

```text
TASK-001 Repository foundation and typed state ───┐
                                                  ├─► TASK-003 Graph skeleton
TASK-002 Model Gateway contracts ─────────────────┘
                                                        │
                                                        ▼
                                      TASK-004 Understanding and action nodes
                                                        │
                                                        ▼
                                      TASK-005 Checkpoint and thread tests
```

## Scope guardrails

- Phase 1 does not implement enterprise tools or synthetic Golden Case data.
- No write capability is introduced; the runtime capability remains READ_ONLY.
- Business decisions remain model-driven.
- Concrete model providers and model names remain configuration concerns.
- Each task must satisfy its own acceptance criteria before dependent work starts.

## Initial implementation choice

The initial runtime uses Python 3.11 with a `src/` package layout. This is an
implementation choice compatible with the documented LangGraph architecture;
it does not change graph topology, state semantics, or safety boundaries.
