"""Provider-neutral model contracts and gateway for OpsMind."""

from opsmind.models.contracts import (
    ModelMessage,
    ModelProfile,
    ModelRequest,
    ModelResponse,
    ModelRole,
    ModelRoute,
    ModelTask,
    ModelUsage,
    StructuredModelResponse,
)
from opsmind.models.errors import (
    ModelGatewayError,
    ModelInvocationError,
    ModelProviderAlreadyRegisteredError,
    ModelProviderNotFoundError,
    ModelRouteConfigurationError,
    ModelRouteNotFoundError,
    ModelStructuredOutputError,
    StructuredFailureCategory,
    StructuredNodeFailureDiagnostic,
)
from opsmind.models.gateway import ModelGateway
from opsmind.models.providers import (
    DeepSeekProvider,
    MockInvocation,
    MockModelProvider,
    MockResponseQueueExhaustedError,
    ModelProvider,
)
from opsmind.models.runtime import build_deepseek_gateway
from opsmind.models.settings import DeepSeekSettings

__all__ = [
    "DeepSeekProvider",
    "DeepSeekSettings",
    "MockInvocation",
    "MockModelProvider",
    "MockResponseQueueExhaustedError",
    "ModelGateway",
    "ModelGatewayError",
    "ModelInvocationError",
    "ModelMessage",
    "ModelProfile",
    "ModelProvider",
    "ModelProviderAlreadyRegisteredError",
    "ModelProviderNotFoundError",
    "ModelRequest",
    "ModelResponse",
    "ModelRole",
    "ModelRoute",
    "ModelRouteConfigurationError",
    "ModelRouteNotFoundError",
    "ModelStructuredOutputError",
    "ModelTask",
    "ModelUsage",
    "StructuredFailureCategory",
    "StructuredNodeFailureDiagnostic",
    "StructuredModelResponse",
    "build_deepseek_gateway",
]
