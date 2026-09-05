"""Application factory for the OpsMind HTTP runtime."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from time import perf_counter
from typing import Annotated, cast
from uuid import uuid4

from fastapi import Depends, FastAPI, Query, Request
from fastapi import Path as PathParameter
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from opsmind.agent.errors import AgentInputError
from opsmind.agent.graph import bounded_trace_summary
from opsmind.agent.grounding import stable_evidence_items
from opsmind.api.composition import build_runtime
from opsmind.api.run_observability import (
    normalized_error_code,
    persist_chat_success,
    safe_failure_steps,
)
from opsmind.api.runtime import AgentRunResult, OpsAgentRuntime
from opsmind.api.schemas import (
    AgentTraceStep,
    ChatDecision,
    ChatEvidence,
    ChatHandoff,
    ChatRequest,
    ChatResponse,
    ChatUnderstanding,
    ErrorDetail,
    ErrorResponse,
    HealthResponse,
)
from opsmind.api.settings import RuntimeSettings
from opsmind.models import (
    ModelInvocationError,
    ModelStructuredOutputError,
    StructuredNodeFailureDiagnostic,
)
from opsmind.runs import (
    AgentRun,
    AgentRunSummary,
    RunNotFoundError,
    RunPersistenceError,
    RunPersistenceService,
    RunRepository,
    SQLiteRunRepository,
)
from opsmind.state import IdentityState, OpsAgentState

LOGGER = logging.getLogger("opsmind.api")
RequestHandler = Callable[[Request], Awaitable[Response]]


def _log_structured_node_failure(
    request: Request,
    error: ModelInvocationError | ModelStructuredOutputError,
) -> None:
    """Log an allowlisted, request-correlated structured-node diagnostic."""

    diagnostic = getattr(error, "diagnostic", None)
    if not isinstance(diagnostic, StructuredNodeFailureDiagnostic):
        return
    # Keep this record deliberately explicit.  In particular, do not pass
    # ``error``/``exc_info``: provider messages and exception chains may carry
    # prompts, payloads, credentials, or user input.
    LOGGER.warning(
        "structured_node_failure request_id=%s node=%s "
        "expected_schema_name=%s logical_profile=%s category=%s",
        _request_id(request),
        diagnostic.node,
        diagnostic.expected_schema_name,
        diagnostic.logical_profile,
        diagnostic.category,
    )


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
            run_id=getattr(request.state, "run_id", None),
        )
    )
    request_id = payload.error.request_id
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(exclude_none=True),
        headers={"X-Request-ID": request_id},
    )


def _trace_summary(result: AgentRunResult, node: str) -> str:
    if node == "understand_request":
        understanding = result.state.understanding
        return bounded_trace_summary(
            f"{understanding.primary_intent} / {understanding.request_type}"
        )
    decision = result.state.decision
    return bounded_trace_summary(
        decision.action.value if decision.action is not None else "ACTION_UNKNOWN"
    )


def _trace(result: AgentRunResult) -> list[AgentTraceStep]:
    if result.events:
        return [
            AgentTraceStep(
                node=event.node,
                task=event.task,
                profile=event.profile,
                status=event.status,
                summary=event.summary,
            )
            for event in result.events
        ]
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
    run_id: str,
    thread_id: str,
) -> ChatResponse:
    understanding = ChatUnderstanding.model_validate(
        result.state.understanding.model_dump()
    )
    decision = ChatDecision.model_validate(result.state.decision.model_dump())
    state_status = result.state.task.status
    status = {
        "WAITING_USER": "waiting_user",
        "TRANSFERRED": "transferred",
        "RESOLVED": "completed",
        "CLOSED": "closed",
    }.get(state_status.value if state_status is not None else "", "decision_ready")
    handoff = (
        ChatHandoff(
            required=result.state.handoff.required,
            summary=result.state.handoff.summary,
        )
        if result.state.handoff.required or result.state.handoff.summary
        else None
    )
    return ChatResponse(
        request_id=request_id,
        run_id=run_id,
        thread_id=thread_id,
        status=status,
        final_status=state_status.value if state_status is not None else None,
        understanding=understanding,
        decision=decision,
        trace=_trace(result),
        final_reply=result.state.response.message,
        evidence=[
            ChatEvidence.model_validate(item.model_dump())
            for item in stable_evidence_items(result.state.evidence.items)
        ],
        handoff=handoff,
    )


def _runtime_dependency(request: Request) -> OpsAgentRuntime:
    return cast(OpsAgentRuntime, request.app.state.runtime)


def _run_service_dependency(request: Request) -> RunPersistenceService:
    return cast(RunPersistenceService, request.app.state.run_persistence)


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
            run_id = getattr(request.state, "run_id", None)
            LOGGER.info(
                "api_request request_id=%s run_id=%s thread_id=%s endpoint=%s "
                "status=%d latency_ms=%.3f",
                request.state.request_id,
                run_id if isinstance(run_id, str) else "-",
                thread_id if isinstance(thread_id, str) else "-",
                request.url.path,
                status_code,
                elapsed_ms,
            )


def create_app(
    *,
    runtime: OpsAgentRuntime | None = None,
    settings: RuntimeSettings | None = None,
    run_repository: RunRepository | None = None,
) -> FastAPI:
    """Create an explicitly composed and dependency-injectable application."""

    configured_settings = settings or RuntimeSettings.from_env()
    configured_runtime = runtime or build_runtime(configured_settings)
    configured_repository = run_repository or SQLiteRunRepository(
        configured_settings.run_store_path
    )
    app = FastAPI(title="OpsMind API", version="0.1.0")
    app.state.runtime = configured_runtime
    app.state.run_repository = configured_repository
    app.state.run_persistence = RunPersistenceService(
        configured_repository,
        app_version=app.version,
        build_sha=configured_settings.build_sha,
    )
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

    @app.exception_handler(RunNotFoundError)
    async def run_not_found_handler(
        request: Request,
        exc: RunNotFoundError,
    ) -> JSONResponse:
        del exc
        return _error_response(
            request,
            status_code=404,
            code="RUN_NOT_FOUND",
            message="Agent run was not found",
        )

    @app.exception_handler(RunPersistenceError)
    async def run_persistence_handler(
        request: Request,
        exc: RunPersistenceError,
    ) -> JSONResponse:
        LOGGER.error(
            "run_persistence_unavailable request_id=%s run_id=%s error_type=%s",
            _request_id(request),
            getattr(request.state, "run_id", "-"),
            type(exc).__name__,
        )
        return _error_response(
            request,
            status_code=503,
            code="RUN_PERSISTENCE_UNAVAILABLE",
            message="Agent run persistence is unavailable",
        )

    @app.exception_handler(ModelStructuredOutputError)
    async def structured_output_handler(
        request: Request,
        exc: ModelStructuredOutputError,
    ) -> JSONResponse:
        _log_structured_node_failure(request, exc)
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
        _log_structured_node_failure(request, exc)
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
            503: {"model": ErrorResponse},
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
        run_persistence: Annotated[
            RunPersistenceService,
            Depends(_run_service_dependency),
        ],
    ) -> ChatResponse:
        thread_id = payload.thread_id or str(uuid4())
        request.state.thread_id = thread_id
        active_run = run_persistence.start(
            request_id=_request_id(request),
            thread_id=thread_id,
            input_message=payload.message,
            source_context=payload.source_context,
        )
        request.state.run_id = active_run.run_id
        user_id = payload.source_context.get("user_id")
        site_id = payload.source_context.get("site_id")
        state = OpsAgentState(
            identity=IdentityState(
                user_id=user_id if isinstance(user_id, str) else None,
                site_id=site_id if isinstance(site_id, str) else None,
                source_context=payload.source_context,
            ),
            conversation={
                "thread_id": thread_id,
                "original_query": payload.message,
                "current_query": payload.message,
            },
        )
        try:
            result = await agent_runtime.run_with_trace(state)
            response = _chat_response(
                result,
                request_id=_request_id(request),
                run_id=active_run.run_id,
                thread_id=thread_id,
            )
        except Exception as exc:
            try:
                run_persistence.fail(
                    active_run,
                    error_code=normalized_error_code(exc),
                    steps=safe_failure_steps(exc),
                )
            except RunPersistenceError as persistence_error:
                raise persistence_error from None
            raise

        persist_chat_success(run_persistence, active_run, response)
        return response

    @app.get(
        "/api/v1/runs",
        response_model=list[AgentRunSummary],
        responses={503: {"model": ErrorResponse}},
        tags=["runs"],
    )
    async def list_runs(
        run_persistence: Annotated[
            RunPersistenceService,
            Depends(_run_service_dependency),
        ],
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ) -> list[AgentRunSummary]:
        return run_persistence.list(limit=limit)

    @app.get(
        "/api/v1/runs/{run_id}",
        response_model=AgentRun,
        responses={
            404: {"model": ErrorResponse},
            503: {"model": ErrorResponse},
        },
        tags=["runs"],
    )
    async def get_run(
        run_id: Annotated[
            str,
            PathParameter(min_length=1, max_length=128),
        ],
        run_persistence: Annotated[
            RunPersistenceService,
            Depends(_run_service_dependency),
        ],
    ) -> AgentRun:
        return run_persistence.get(run_id)

    return app
