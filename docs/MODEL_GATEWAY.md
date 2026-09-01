# OpsMind Model Gateway

The Model Gateway is the single model-access boundary for OpsMind. Agent nodes
select a logical profile and task, then submit provider-neutral messages. They
do not instantiate or import a concrete provider client.

## Contracts

`ModelProfile` identifies a logical cost/quality tier:

- `ModelProfile.CHEAP` (`CHEAP`)
- `ModelProfile.STRONG` (`STRONG`)
- `ModelProfile.FALLBACK` (`FALLBACK`)

Configuration mappings may use the lowercase logical names (`cheap`,
`strong`, `fallback`) as keys; they are normalized to the enum members.

`ModelTask` identifies why the call is being made. It is observability and
evaluation metadata, not a business router. `ModelMessage` contains a
provider-neutral `ModelRole` and text content. `ModelRequest` combines a task,
profile, non-empty message list, and JSON-compatible metadata for tracing and
debugging.

`ModelResponse` contains text plus the selected provider/model and optional
finish reason, usage, latency, and request ID. Usage token counts are
non-negative, and latency is finite and non-negative. Providers may leave
optional observability fields as `None` when they do not supply them.

## Routes and providers

`ModelRoute` explicitly maps a logical profile to a provider registration name
and configurable model name:

```python
routes = {
    ModelProfile.CHEAP: ModelRoute(
        profile=ModelProfile.CHEAP,
        provider="mock",
        model="mock-cheap",
    ),
}
gateway = ModelGateway(routes=routes, providers={"mock": provider})
```

`ModelProvider` is an async protocol with `invoke` and
`invoke_structured` methods. The structured method returns a
`StructuredModelResponse[T]`, so an adapter can supply output metadata without
leaking its SDK schema. A provider adapter owns all SDK-specific details; the
gateway only performs profile routing, provider lookup, invocation, and
response validation. Provider registration names cannot be silently
overwritten.

## Calling the gateway

Text and structured calls are both async:

```python
request = ModelRequest(
    task=ModelTask.REQUEST_UNDERSTANDING,
    profile=ModelProfile.CHEAP,
    messages=[ModelMessage(role=ModelRole.USER, content="...")],
    metadata={"thread_id": "thread-123", "node": "understand_request"},
)
text_response = await gateway.invoke(request)
structured_response = await gateway.invoke_structured(request, UnderstandingSchema)
understanding = structured_response.parsed
```

`invoke_structured` accepts a Pydantic `BaseModel` subclass and returns a
`StructuredModelResponse[T]`. Its `parsed` field is the caller's Pydantic
model instance, and its `response` field retains provider/model, usage,
latency, finish reason, and request ID metadata. Invalid payloads are never
returned as an unchecked dictionary; they raise
`ModelStructuredOutputError`. Callers that do not need metadata can use
`invoke_structured_value` to receive only the validated model instance.

## Error boundary

Callers can distinguish configuration failures from invocation and parsing
failures:

- `ModelRouteNotFoundError`: the requested profile has no route;
- `ModelProviderNotFoundError`: a route references an unregistered provider;
- `ModelInvocationError`: the provider failed or returned an invalid text
  response;
- `ModelStructuredOutputError`: structured output failed schema validation;
- `ModelRouteConfigurationError`: a route is malformed or duplicated.

All are subclasses of `ModelGatewayError`.

## Mock provider

`MockModelProvider` is a deterministic test adapter. It consumes predefined
text or structured responses from queues and records every request, selected
model, profile, task, and message list in `history`/`invocations`. This lets
future Agent-node tests assert profile routing without network calls or
provider credentials. History access returns detached snapshots, so test code
cannot mutate records held by the provider.

## DeepSeek provider

`DeepSeekProvider` is the first real `ModelProvider` implementation. It uses
DeepSeek's OpenAI-compatible async Responses API and is registered as
`deepseek`. All DeepSeek-specific request fields, response shapes, SDK usage,
thinking configuration, and error normalization remain inside the provider and
its configuration/runtime composition modules. The Agent graph, nodes, state,
and prompts continue to use the existing provider-neutral gateway contract.

Plain calls send provider-neutral messages as Responses API message items and
return a `ModelResponse`. Structured calls follow this validation path:

```text
Pydantic response model
  -> model_json_schema()
  -> Responses API text.format = json_schema
  -> JSON text extraction and parsing
  -> response_model.model_validate(...)
  -> StructuredModelResponse[T]
```

Empty or malformed text responses and transport failures raise
`ModelInvocationError`. Empty JSON, invalid/truncated JSON, unexpected response
shapes, and Pydantic schema mismatches raise `ModelStructuredOutputError` for a
structured call. The provider does not synthesize business defaults or perform
semantic retries. SDK-default safe transport retries are left unchanged.

Provider metadata is normalized where available:

- DeepSeek response status becomes `finish_reason`;
- input, output, and total token counts become `ModelUsage`;
- the SDK/HTTP request ID is mapped when available; a response ID is not
  mislabeled as a request ID;
- latency is measured with a monotonic clock;
- absent optional metadata remains `None` rather than a fabricated value.

## Runtime configuration

Build a gateway explicitly; there is no global provider or gateway singleton:

```python
from opsmind.models import DeepSeekSettings, build_deepseek_gateway

settings = DeepSeekSettings.from_env()
gateway = build_deepseek_gateway(settings)
```

The runtime factory installs these routes:

| Profile | Provider | Default model |
| --- | --- | --- |
| `CHEAP` | `deepseek` | `deepseek-v4-flash` |
| `STRONG` | `deepseek` | `deepseek-v4-pro` |

The current Agent kernel continues to select only `CHEAP`. Configuring a strong
route does not cause any node to upgrade itself.

Supported environment variables are:

| Variable | Required | Default |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | yes | none |
| `DEEPSEEK_BASE_URL` | no | `https://api.deepseek.com` |
| `OPSMIND_CHEAP_MODEL` | no | `deepseek-v4-flash` |
| `OPSMIND_STRONG_MODEL` | no | `deepseek-v4-pro` |
| `DEEPSEEK_TIMEOUT_SECONDS` | no | `60` |
| `DEEPSEEK_REASONING_EFFORT` | no | `none` |

The first kernel integration uses non-thinking mode. Thinking effort is a
provider configuration choice and is not switched based on the model task.

`DEEPSEEK_API_KEY` must be non-empty. It is held as a Pydantic `SecretStr` and
is redacted from settings/provider repr, model dumps, JSON, logs, and normalized
exception messages. `.env.example` contains only an empty placeholder; never
commit a real key.

## Live kernel smoke test

Normal `pytest` runs exclude the `live` marker and are fully offline. To run
the opt-in real-model connectivity and contract smoke test:

```bash
DEEPSEEK_API_KEY=... uv run --frozen pytest -m live
```

Without `DEEPSEEK_API_KEY`, that explicitly selected test is skipped. The smoke
test runs the unchanged `OpsAgentState -> LangGraph -> ModelGateway` path for
`WO20260001为什么一直没处理？` and checks that understanding and action-decision
outputs pass their typed state contracts. It intentionally does not assert a
specific business classification.
