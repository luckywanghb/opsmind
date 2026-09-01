"""Explicit runtime composition for real model providers."""

from __future__ import annotations

from opsmind.models.contracts import ModelProfile, ModelRoute
from opsmind.models.gateway import ModelGateway
from opsmind.models.providers.deepseek import DeepSeekProvider
from opsmind.models.settings import DeepSeekSettings


def build_deepseek_gateway(
    settings: DeepSeekSettings,
    *,
    provider: DeepSeekProvider | None = None,
) -> ModelGateway:
    """Build an explicitly owned gateway with cheap and strong DeepSeek routes."""

    deepseek = provider or DeepSeekProvider(settings)
    return ModelGateway(
        routes={
            ModelProfile.CHEAP: ModelRoute(
                profile=ModelProfile.CHEAP,
                provider=DeepSeekProvider.provider_name,
                model=settings.cheap_model,
            ),
            ModelProfile.STRONG: ModelRoute(
                profile=ModelProfile.STRONG,
                provider=DeepSeekProvider.provider_name,
                model=settings.strong_model,
            ),
        },
        providers={DeepSeekProvider.provider_name: deepseek},
    )
