"""Application factory for the OpsMind HTTP runtime."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from time import perf_counter
from typing import Annotated, cast
from uuid import uuid4

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from opsmind.agent.errors import AgentInputError
from opsmind.api.composition import build_runtime
from opsmind.api.runtime import AgentRunResult, OpsAgentRuntime
from opsmind.api.schemas import (
    AgentTraceStep,
    ChatDecision,
    ChatRequest,
    ChatResponse,
    ChatUnderstanding,
    ErrorDetail,
    ErrorResponse,
    HealthResponse,
)
from opsmind.api.settings import RuntimeSettings
from opsmind.models import ModelInvocationError, ModelStructuredOutputError
from opsmind.state import IdentityState, OpsAgentState

LOGGER = logging.getLogger("opsmind.api")
RequestHandler = Callable[[Request], Awaitable[Response]]


def _request_id(request: Request) -> str:
    request_id = getattr(request.state, "request_id", None)
    return request_id if isinstance(request_id, str) else str(uuid4())


def _error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
) -> JSONResponse:
    payload = ErrorResponse(
        error=ErrorDetail(
            code=code,
            message=message,
            request_id=_request_id(request),
        )
    )
    return JSONResponse(status_code=status_code, content=payload.model_dump())


def _trace_summary(result: AgentRunResult, node: str) -> str:
    if node == "understand_request":
        understanding = result.state.understanding
        return f"{understanding.primary_intent} / {understanding.request_type}"
    decision = result.state.decision
    return f"{decision.action}: {decision.goal}"


def _trace(result: AgentRunResult) -> list[AgentTraceStep]:
    steps: list[AgentTraceStep] = []
    for invocation in result.invocations:
        node = invocation.request.metadata.get("node")
        if not isinstance(node, str) or not node:
            continue
        steps.append(
            AgentTraceStep(
                node=node,
                task=invocation.request.task,
                profile=invocation.request.profile,
                summary=_trace_summary(result, node),
            )
        )
    return steps


def _chat_response(
    result: AgentRunResult,
    *,
    request_id: str,
    thread_id: str,
) -> ChatResponse:
    understanding = ChatUnderstanding.model_validate(
        result.state.understanding.model_dump()
    )
    decision = ChatDecision.model_validate(result.state.decision.model_dump())
    return ChatResponse(
        request_id=request_id,
        thread_id=thread_id,
        understanding=understanding,
        decision=decision,
        trace=_trace(result),
    )


def _runtime_dependency(request: Request) -> OpsAgentRuntime:
    return cast(OpsAgentRuntime, request.app.state.runtime)


class _RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: RequestHandler,
    ) -> Response:
        request.state.request_id = str(uuid4())
        started = perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-ID"] = request.state.request_id
            return response
        finally:
            elapsed_ms = (perf_counter() - started) * 1_000
            thread_id = getattr(request.state, "thread_id", None)
            LOGGER.info(
                "api_request request_id=%s thread_id=%s endpoint=%s "
                "status=%d latency_ms=%.3f",
                request.state.request_id,
                thread_id if isinstance(thread_id, str) else "-",
                request.url.path,
                status_code,
                elapsed_ms,
            )


def create_app(
    *,
    runtime: OpsAgentRuntime | None = None,
    settings: RuntimeSettings | None = None,
) -> FastAPI:
    """Create an explicitly composed and dependency-injectable application."""

    configured_runtime = runtime or build_runtime(
        settings or RuntimeSettings.from_env()
    )
    app = FastAPI(title="OpsMind API", version="0.1.0")
    app.state.runtime = configured_runtime
    app.add_middleware(_RequestContextMiddleware)

    @app.exception_handler(RequestValidationError)
    async def request_validation_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        del exc
        return _error_response(
            request,
            status_code=422,
            code="REQUEST_VALIDATION_FAILED",
            message="Request validation failed",
        )

    @app.exception_handler(AgentInputError)
    async def agent_input_handler(
        request: Request,
        exc: AgentInputError,
    ) -> JSONResponse:
        del exc
        return _error_response(
            request,
            status_code=400,
            code="INVALID_AGENT_INPUT",
            message="Agent input is invalid",
        )

    @app.exception_handler(ModelStructuredOutputError)
    async def structured_output_handler(
        request: Request,
        exc: ModelStructuredOutputError,
    ) -> JSONResponse:
        del exc
        return _error_response(
            request,
            status_code=502,
            code="MODEL_STRUCTURED_OUTPUT_INVALID",
            message="Model returned invalid structured output",
        )

    @app.exception_handler(ModelInvocationError)
    async def model_invocation_handler(
        request: Request,
        exc: ModelInvocationError,
    ) -> JSONResponse:
        del exc
        return _error_response(
            request,
            status_code=502,
            code="MODEL_INVOCATION_FAILED",
            message="Model invocation failed",
        )

    @app.exception_handler(Exception)
    async def unexpected_error_handler(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        LOGGER.error(
            "unexpected_api_error request_id=%s error_type=%s",
            _request_id(request),
            type(exc).__name__,
        )
        return _error_response(
            request,
            status_code=500,
            code="INTERNAL_SERVER_ERROR",
            message="Internal server error",
        )

    @app.get(
        "/api/v1/health",
        response_model=HealthResponse,
        tags=["system"],
    )
    async def health() -> HealthResponse:
        return HealthResponse()

    @app.post(
        "/api/v1/chat",
        response_model=ChatResponse,
        responses={
            400: {"model": ErrorResponse},
            422: {"model": ErrorResponse},
            500: {"model": ErrorResponse},
            502: {"model": ErrorResponse},
        },
        tags=["agent"],
    )
    async def chat(
        payload: ChatRequest,
        request: Request,
        agent_runtime: Annotated[
            OpsAgentRuntime,
            Depends(_runtime_dependency),
        ],
    ) -> ChatResponse:
        thread_id = payload.thread_id or str(uuid4())
        request.state.thread_id = thread_id
        state = OpsAgentState(
            identity=IdentityState(source_context=payload.source_context),
            conversation={
                "thread_id": thread_id,
                "original_query": payload.message,
                "current_query": payload.message,
            },
        )
        result = await agent_runtime.run_with_trace(state)
        return _chat_response(
            result,
            request_id=_request_id(request),
            thread_id=thread_id,
        )

    return app
