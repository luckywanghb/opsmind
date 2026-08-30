"""Explicit profile-to-provider routing for model invocations."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import TypeAlias, TypeVar

from pydantic import BaseModel, ValidationError

from opsmind.models.contracts import (
    ModelProfile,
    ModelRequest,
    ModelResponse,
    ModelRoute,
)
from opsmind.models.errors import (
    ModelGatewayError,
    ModelInvocationError,
    ModelProviderAlreadyRegisteredError,
    ModelProviderNotFoundError,
    ModelRouteConfigurationError,
    ModelRouteNotFoundError,
    ModelStructuredOutputError,
)
from opsmind.models.providers.base import ModelProvider

T = TypeVar("T", bound=BaseModel)

RouteMapping: TypeAlias = (
    Mapping[ModelProfile, ModelRoute]
    | Mapping[str, ModelRoute | Mapping[str, object]]
)
RouteInput: TypeAlias = RouteMapping | Iterable[ModelRoute | Mapping[str, object]]


def _coerce_profile(value: ModelProfile | str) -> ModelProfile:
    """Accept enum values and enum member names in configuration mappings."""

    if isinstance(value, ModelProfile):
        return value
    try:
        return ModelProfile(value)
    except ValueError:
        try:
            return ModelProfile[value]
        except KeyError as exc:
            raise ValueError(f"unknown model profile {value!r}") from exc


class ModelGateway:
    """Route provider-neutral requests to explicitly registered providers.

    The gateway performs no prompt construction or business routing.  A
    request's logical profile selects one configured :class:`ModelRoute`; the
    route selects a provider name and model name, and the provider performs the
    invocation.
    """

    def __init__(
        self,
        routes: RouteInput | None = None,
        providers: Mapping[str, ModelProvider] | None = None,
    ) -> None:
        self._routes: dict[ModelProfile, ModelRoute] = {}
        self._providers: dict[str, ModelProvider] = {}

        if routes is not None:
            self._load_routes(routes)
        if providers is not None:
            self._load_providers(providers)

    @property
    def routes(self) -> Mapping[ModelProfile, ModelRoute]:
        """A snapshot of configured routes."""

        return dict(self._routes)

    @property
    def providers(self) -> Mapping[str, ModelProvider]:
        """A snapshot of registered providers."""

        return dict(self._providers)

    def _load_routes(
        self,
        routes: RouteInput,
    ) -> None:
        if isinstance(routes, Mapping):
            for key, route in routes.items():
                parsed_route = self._parse_route(route)
                try:
                    profile = _coerce_profile(key)
                except ValueError as exc:
                    raise ModelRouteConfigurationError(str(exc)) from exc
                if parsed_route.profile is not profile:
                    raise ModelRouteConfigurationError(
                        "route profile does not match its configuration key: "
                        f"{parsed_route.profile!r} != {profile!r}"
                    )
                self._add_route(profile, parsed_route)
            return

        for route in routes:
            parsed_route = self._parse_route(route)
            self._add_route(parsed_route.profile, parsed_route)

    @staticmethod
    def _parse_route(
        route: ModelRoute | Mapping[str, object],
    ) -> ModelRoute:
        try:
            return ModelRoute.model_validate(route)
        except ValidationError as exc:
            raise ModelRouteConfigurationError(
                f"invalid model route configuration: {exc}"
            ) from exc

    def _add_route(self, profile: ModelProfile, route: ModelRoute) -> None:
        if profile in self._routes:
            raise ModelRouteConfigurationError(
                f"model route for profile {profile!r} is already configured"
            )
        self._routes[profile] = route

    def _load_providers(self, providers: Mapping[str, ModelProvider]) -> None:
        for name, provider in providers.items():
            self.register_provider(name, provider)

    def register_provider(self, name: str, provider: ModelProvider) -> None:
        """Register a provider adapter without allowing accidental overwrite."""

        if not isinstance(name, str) or not name.strip():
            raise ValueError("provider name must not be blank")
        if name in self._providers:
            raise ModelProviderAlreadyRegisteredError(name)
        self._providers[name] = provider

    def register_route(self, route: ModelRoute) -> None:
        """Add one route after gateway construction."""

        self._add_route(route.profile, ModelRoute.model_validate(route))

    def _route_for(self, request: ModelRequest) -> ModelRoute:
        route = self._routes.get(request.profile)
        if route is None:
            raise ModelRouteNotFoundError(request.profile)
        return route

    def _provider_for(
        self,
        route: ModelRoute,
        *,
        profile: ModelProfile,
    ) -> ModelProvider:
        provider = self._providers.get(route.provider)
        if provider is None:
            raise ModelProviderNotFoundError(route.provider, profile)
        return provider

    @staticmethod
    def _validated_request(request: ModelRequest) -> ModelRequest:
        return ModelRequest.model_validate(request)

    async def invoke(self, request: ModelRequest) -> ModelResponse:
        """Invoke the provider selected by ``request.profile``."""

        validated_request = self._validated_request(request)
        route = self._route_for(validated_request)
        provider = self._provider_for(route, profile=validated_request.profile)

        try:
            response = await provider.invoke(
                validated_request,
                model=route.model,
            )
        except ModelGatewayError:
            raise
        except Exception as exc:
            raise ModelInvocationError(
                "model provider invocation failed for "
                f"profile {validated_request.profile!r}, "
                f"provider {route.provider!r}, model {route.model!r}"
            ) from exc

        try:
            return ModelResponse.model_validate(response)
        except ValidationError as exc:
            raise ModelInvocationError(
                "model provider returned an invalid response for "
                f"profile {validated_request.profile!r}"
            ) from exc

    async def invoke_structured(
        self,
        request: ModelRequest,
        response_model: type[T],
    ) -> T:
        """Invoke and validate structured output against ``response_model``."""

        if not isinstance(response_model, type) or not issubclass(
            response_model, BaseModel
        ):
            raise ModelStructuredOutputError(
                "response_model must be a Pydantic BaseModel subclass"
            )

        validated_request = self._validated_request(request)
        route = self._route_for(validated_request)
        provider = self._provider_for(route, profile=validated_request.profile)

        try:
            result = await provider.invoke_structured(
                validated_request,
                response_model,
                model=route.model,
            )
        except ModelStructuredOutputError:
            raise
        except ModelGatewayError:
            raise
        except ValidationError as exc:
            raise ModelStructuredOutputError(
                "model provider returned structured output that does not "
                f"match {response_model.__name__}"
            ) from exc
        except Exception as exc:
            raise ModelInvocationError(
                "structured model provider invocation failed for "
                f"profile {validated_request.profile!r}, "
                f"provider {route.provider!r}, model {route.model!r}"
            ) from exc

        try:
            return response_model.model_validate(result)
        except (ValidationError, TypeError, ValueError) as exc:
            raise ModelStructuredOutputError(
                "model provider returned structured output that does not "
                f"match {response_model.__name__}"
            ) from exc
