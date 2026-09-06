"""Application factory for the OpsMind HTTP runtime."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
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
from opsmind.api.composition import build_runtime
from opsmind.api.runtime import OpsAgentRuntime
from opsmind.api.schemas import (
    ChatRequest,
    ChatResponse,
    ErrorDetail,
    ErrorResponse,
    EvalRunRequest,
    HealthResponse,
)
from opsmind.api.settings import RuntimeSettings
from opsmind.evals import (
    EvalJob,
    EvalJobSummary,
    EvalNotFoundError,
    EvalPersistenceError,
    EvalPersistenceService,
    EvalRepository,
    EvalRunner,
    EvalRunnerError,
    EvalSuiteLoader,
    EvalSuiteLoadError,
    SQLiteEvalRepository,
)
from opsmind.execution import AgentExecutionError, AgentExecutionService
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
from opsmind.state import OpsAgentState

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


def _run_service_dependency(request: Request) -> RunPersistenceService:
    return cast(RunPersistenceService, request.app.state.run_persistence)


def _execution_dependency(request: Request) -> AgentExecutionService:
    return cast(AgentExecutionService, request.app.state.execution_service)


def _eval_runner_dependency(request: Request) -> EvalRunner:
    return cast(EvalRunner, request.app.state.eval_runner)


def _eval_persistence_dependency(request: Request) -> EvalPersistenceService:
    return cast(EvalPersistenceService, request.app.state.eval_persistence)


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
    eval_repository: EvalRepository | None = None,
    eval_suite_loader: EvalSuiteLoader | None = None,
    eval_runner: EvalRunner | None = None,
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
    app.state.execution_service = AgentExecutionService(
        configured_runtime,
        app.state.run_persistence,
        state_factory=OpsAgentState,
    )
    eval_store_path: str | Path = configured_settings.run_store_path
    repository_path = getattr(configured_repository, "path", None)
    if isinstance(repository_path, (str, Path)):
        # The default eval schema belongs in the same SQLite file as the run
        # schema.  This also keeps dependency-injected SQLite repositories
        # isolated in tests without requiring a second path argument.
        eval_store_path = repository_path
    configured_eval_repository = eval_repository or SQLiteEvalRepository(
        eval_store_path
    )
    app.state.eval_repository = configured_eval_repository
    app.state.eval_persistence = EvalPersistenceService(
        configured_eval_repository,
        app_version=app.version,
        build_sha=configured_settings.build_sha,
        run_repository=configured_repository,
    )
    configured_loader = eval_suite_loader or EvalSuiteLoader()
    app.state.eval_runner = eval_runner or EvalRunner(
        loader=configured_loader,
        execution_service=app.state.execution_service,
        persistence=app.state.eval_persistence,
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

    @app.exception_handler(EvalSuiteLoadError)
    async def eval_suite_handler(
        request: Request,
        exc: EvalSuiteLoadError,
    ) -> JSONResponse:
        del exc
        return _error_response(
            request,
            status_code=422,
            code="EVAL_SUITE_INVALID",
            message="Evaluation suite is invalid",
        )

    @app.exception_handler(EvalNotFoundError)
    async def eval_not_found_handler(
        request: Request,
        exc: EvalNotFoundError,
    ) -> JSONResponse:
        del exc
        return _error_response(
            request,
            status_code=404,
            code="EVAL_NOT_FOUND",
            message="Evaluation job was not found",
        )

    @app.exception_handler(EvalPersistenceError)
    async def eval_persistence_handler(
        request: Request,
        exc: EvalPersistenceError,
    ) -> JSONResponse:
        LOGGER.error(
            "eval_persistence_unavailable request_id=%s error_type=%s",
            _request_id(request),
            type(exc).__name__,
        )
        return _error_response(
            request,
            status_code=503,
            code="EVAL_PERSISTENCE_UNAVAILABLE",
            message="Evaluation persistence is unavailable",
        )

    @app.exception_handler(EvalRunnerError)
    async def eval_runner_handler(
        request: Request,
        exc: EvalRunnerError,
    ) -> JSONResponse:
        del exc
        return _error_response(
            request,
            status_code=500,
            code="EVAL_RUN_FAILED",
            message="Evaluation run failed",
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
        execution_service: Annotated[
            AgentExecutionService,
            Depends(_execution_dependency),
        ],
    ) -> ChatResponse:
        thread_id = payload.thread_id or str(uuid4())
        request.state.thread_id = thread_id
        try:
            result = await execution_service.execute(
                message=payload.message,
                source_context=payload.source_context,
                request_id=_request_id(request),
                thread_id=thread_id,
            )
        except AgentExecutionError as exc:
            request.state.run_id = exc.run_id
            raise exc.cause from None
        except RunPersistenceError as exc:
            run_id = getattr(exc, "run_id", None)
            if isinstance(run_id, str):
                request.state.run_id = run_id
            raise
        request.state.run_id = result.run_id
        return result.response

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

    @app.post(
        "/api/v1/evals/run",
        response_model=EvalJob,
        responses={
            422: {"model": ErrorResponse},
            500: {"model": ErrorResponse},
            503: {"model": ErrorResponse},
        },
        tags=["evals"],
    )
    async def run_eval(
        payload: EvalRunRequest,
        eval_runner: Annotated[
            EvalRunner,
            Depends(_eval_runner_dependency),
        ],
    ) -> EvalJob:
        return await eval_runner.run_suite(payload.suite_id)

    @app.get(
        "/api/v1/evals",
        response_model=list[EvalJobSummary],
        responses={503: {"model": ErrorResponse}},
        tags=["evals"],
    )
    async def list_evals(
        eval_persistence: Annotated[
            EvalPersistenceService,
            Depends(_eval_persistence_dependency),
        ],
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
    ) -> list[EvalJobSummary]:
        return eval_persistence.list(limit=limit)

    @app.get(
        "/api/v1/evals/{eval_job_id}",
        response_model=EvalJob,
        responses={
            404: {"model": ErrorResponse},
            503: {"model": ErrorResponse},
        },
        tags=["evals"],
    )
    async def get_eval(
        eval_job_id: Annotated[
            str,
            PathParameter(min_length=1, max_length=128),
        ],
        eval_persistence: Annotated[
            EvalPersistenceService,
            Depends(_eval_persistence_dependency),
        ],
    ) -> EvalJob:
        return eval_persistence.get(eval_job_id)

    return app
