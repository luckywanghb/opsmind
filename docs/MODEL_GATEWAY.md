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

## Future concrete adapters

A future adapter may connect a real model service such as DeepSeek, but that
adapter must remain behind `ModelProvider`. It should be registered under a
configuration name and selected through `ModelRoute`; no Agent node or business
contract should need to know the provider SDK or concrete model details.
