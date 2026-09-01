# OpsMind Agent Kernel

The first runnable OpsMind Agent is a single, dependency-injected LangGraph
run:

```text
START
  ↓
understand_request
  ↓
decide_action
  ↓
END
```

## Node responsibilities

`understand_request` builds a conversation-only context and calls the Model
Gateway with `ModelTask.REQUEST_UNDERSTANDING` and
`ModelProfile.CHEAP`. Its validated `RequestUnderstandingOutput` updates only
`state.understanding`.

`decide_action` receives the state after that update, builds a compact
decision context, and calls the Model Gateway with
`ModelTask.ACTION_DECISION` and `ModelProfile.CHEAP`. Its validated
`ActionDecisionOutput` updates only `state.decision`.

Both nodes are asynchronous and receive the gateway explicitly. Nodes do not
instantiate providers or make keyword/rule-based business decisions.

## State boundary and context assembly

`OpsAgentState` is the sole canonical business state. LangGraph uses that
Pydantic model directly; no parallel business-state schema or persistence
adapter is required for this kernel.

Each model call receives an explicit projection rather than a serialized full
state. Request understanding sees the current query and, when available, the
original query, summary, previous resolution status, and source context.
Action decision sees the current query, understanding, task objective/status,
facts, compact evidence summaries, and loop counters. Safety, tool internals,
raw evidence, handoff, response, and unrelated metadata are not included.

## Error behavior

The current query is required. Missing or whitespace-only
`conversation.current_query` raises `AgentInputError` before any model call.
Structured output is validated by the gateway and again at the state boundary;
invalid output raises `ModelStructuredOutputError` and is never written into
state. Gateway invocation errors propagate to the caller. The kernel does not
retry or synthesize fallback business decisions.

## Current limitations

This is a single-run kernel only. It has no tools, conditional routing,
loops, persistence/checkpoints, thread resume, interrupts, provider SDK,
retrieval, API server, UI, deployment, or Golden Case runtime branches.
`SEARCH` and other actions are recorded as decisions and the graph then ends.

## Next planned extensions

Future tasks may add bounded action loops, model-driven tool selection,
read-only tool execution, compact evidence review, and persistence/thread
continuity. Human approval interrupts and write capabilities remain deferred
until their own safety and architecture tasks.
