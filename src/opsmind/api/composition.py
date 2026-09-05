"""Provider composition for the HTTP application factory."""

from __future__ import annotations

from typing import TypeVar, cast

from pydantic import BaseModel, ValidationError

from opsmind.agent.schemas import ActionDecisionOutput, RequestUnderstandingOutput
from opsmind.api.runtime import OpsAgentRuntime
from opsmind.api.settings import RuntimeSettings
from opsmind.models import (
    DeepSeekSettings,
    ModelGateway,
    ModelProfile,
    ModelRequest,
    ModelResponse,
    ModelRoute,
    ModelTask,
    StructuredModelResponse,
    build_deepseek_gateway,
)
from opsmind.state import (
    AgentAction,
    PrimaryIntent,
    RequestType,
    RiskSignal,
)

T = TypeVar("T", bound=BaseModel)


class RuntimeConfigurationError(RuntimeError):
    """Raised when the selected runtime cannot be configured explicitly."""


class _DeterministicMockProvider:
    """Reusable offline fixture for local demos and dependency-free tests."""

    async def invoke(
        self,
        request: ModelRequest,
        *,
        model: str,
    ) -> ModelResponse:
        content = {
            ModelTask.CLARIFICATION: "请补充需要查询的对象或范围。",
            ModelTask.RESPONSE_GENERATION: "已根据当前可确认的信息完成回复。",
            ModelTask.HANDOFF_GENERATION: "当前请求需要转人工继续处理。",
        }.get(request.task, "已完成本次请求处理。")
        return ModelResponse(content=content, provider="mock", model=model)

    async def invoke_structured(
        self,
        request: ModelRequest,
        response_model: type[T],
        *,
        model: str,
    ) -> StructuredModelResponse[T]:
        if request.task is ModelTask.REQUEST_UNDERSTANDING:
            payload: BaseModel = RequestUnderstandingOutput(
                primary_intent=PrimaryIntent.OTHER,
                request_type=RequestType.OTHER,
                symptom=None,
                entities={},
                risk_signal=RiskSignal.NONE,
                uncertainty="Deterministic mock mode does not infer intent.",
            )
        else:
            payload = ActionDecisionOutput(
                action=AgentAction.END_CONVERSATION,
                goal="Close the deterministic mock demonstration run.",
                rationale="Deterministic mock mode does not perform live reasoning.",
            )
        parsed = response_model.model_validate(payload.model_dump())
        return cast(
            StructuredModelResponse[T],
            StructuredModelResponse(
                parsed=parsed,
                response=ModelResponse(
                    content="",
                    provider="mock",
                    model=model,
                ),
            ),
        )


def _build_mock_gateway() -> ModelGateway:
    """Build a deterministic, clearly non-production local/test runtime."""

    provider = _DeterministicMockProvider()
    return ModelGateway(
        routes={
            ModelProfile.CHEAP: ModelRoute(
                profile=ModelProfile.CHEAP,
                provider="mock",
                model="opsmind-deterministic-mock",
            )
        },
        providers={"mock": provider},
    )


def build_runtime(settings: RuntimeSettings) -> OpsAgentRuntime:
    """Build exactly the selected runtime; never fall back across providers."""

    if settings.model_provider == "mock":
        return OpsAgentRuntime(_build_mock_gateway())

    try:
        deepseek_settings = DeepSeekSettings.from_env()
    except ValidationError as exc:
        raise RuntimeConfigurationError(
            "DeepSeek runtime configuration is invalid or incomplete"
        ) from exc
    return OpsAgentRuntime(build_deepseek_gateway(deepseek_settings))
