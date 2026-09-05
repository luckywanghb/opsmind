"""Safe diagnostics for failures at structured model-node boundaries."""

from __future__ import annotations

from typing import cast

from opsmind.models.errors import (
    ModelGatewayError,
    ModelInvocationError,
    ModelStructuredOutputError,
    StructuredFailureCategory,
    StructuredNodeFailureDiagnostic,
)


def attach_structured_node_diagnostic(
    error: ModelGatewayError,
    *,
    node: str,
    expected_schema_name: str,
    logical_profile: str,
) -> ModelGatewayError:
    """Attach only allowlisted execution identity to a model-boundary error.

    The original exception remains available to existing callers for typed
    error handling.  API logging reads only ``diagnostic`` and deliberately
    does not include the original exception, its message, or its traceback.
    """

    category: StructuredFailureCategory
    requested_category = getattr(error, "category", None)
    if isinstance(requested_category, str) and requested_category in {
        "empty_output",
        "json_decode",
        "schema_mismatch",
        "response_metadata",
    }:
        category = cast(StructuredFailureCategory, requested_category)
    elif isinstance(error, ModelStructuredOutputError):
        category = "schema_mismatch"
    elif isinstance(error, ModelInvocationError):
        category = "invocation_failed"
    else:
        category = "invocation_failed"

    error.diagnostic = StructuredNodeFailureDiagnostic(
        node=node,
        expected_schema_name=expected_schema_name,
        logical_profile=logical_profile,
        category=category,
    )
    return error


__all__ = ["attach_structured_node_diagnostic"]
