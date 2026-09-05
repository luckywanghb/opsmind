"""Typed contracts for the read-only OpsMind tool runtime.

The Agent model sees the schemas in this module through :class:`ToolSpec`.
Tool adapters return these models, never untyped dictionaries.  The models
are deliberately small because tool output is projected into compact Agent
evidence before it can become long-lived state.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, model_validator

from opsmind.state import StateModel


class ToolMode(StrEnum):
    """Side-effect classification enforced by the tool harness."""

    READ_ONLY = "READ_ONLY"
    WRITE = "WRITE"


class ToolFieldValueKind(StrEnum):
    """Presentation-safe formatting kind for one typed response field."""

    TEXT = "text"
    IDENTIFIER = "identifier"
    ENUM = "enum"
    NUMBER = "number"
    BOOLEAN = "boolean"
    LIST = "list"
    JSON = "json"


class ToolFieldPresentation(StateModel):
    """Bounded metadata used by the deterministic grounded renderer.

    This is deliberately presentation metadata, not a business rule.  The
    response model remains the authority for which fields exist and their
    values; this contract only supplies a localized label/unit and a safe
    formatting hint for a field that the model selected by reference.
    """

    label_zh: str = Field(min_length=1, max_length=100)
    label_en: str | None = Field(default=None, max_length=100)
    unit_zh: str | None = Field(default=None, max_length=40)
    unit_en: str | None = Field(default=None, max_length=40)
    value_kind: ToolFieldValueKind = ToolFieldValueKind.TEXT
    # Optional typed semantic marker used only to choose a bounded limitation
    # sentence. It never routes a tool or changes the value being reported.
    semantic: str = Field(default="fact", min_length=1, max_length=40)

    @classmethod
    def from_schema_field(
        cls,
        field_name: str,
        schema: dict[str, object] | None = None,
    ) -> ToolFieldPresentation:
        """Create a conservative presentation for an unannotated field.

        JSON Schema titles/types are typed contract metadata. The fallback
        never attempts to infer a business label from an intent or user
        wording, so custom read-only tools remain renderable without adding a
        semantic Python branch.
        """

        schema = schema or {}
        field_type = schema.get("type")
        if field_type in {"integer", "number"}:
            kind = ToolFieldValueKind.NUMBER
        elif field_type == "boolean":
            kind = ToolFieldValueKind.BOOLEAN
        elif field_type == "array":
            kind = ToolFieldValueKind.LIST
        elif field_type == "object":
            kind = ToolFieldValueKind.JSON
        else:
            kind = ToolFieldValueKind.TEXT
        title = schema.get("title")
        label = title if isinstance(title, str) and title.strip() else field_name
        return cls(label_zh=label, value_kind=kind)


class ToolResultStatus(StrEnum):
    """Whether a typed adapter result contains usable enterprise evidence."""

    FOUND = "found"
    NOT_FOUND = "not_found"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


NonEmptyToolText = Annotated[str, Field(min_length=1)]


class ToolRequest(StateModel):
    """Strict base class for every registered tool request."""


class ToolResponse(StateModel):
    """Strict base class for every registered tool response."""

    result_status: ToolResultStatus
    message: str | None = None


class WorkOrderQueryRequest(ToolRequest):
    """Request for one work-order status snapshot."""

    work_order_id: NonEmptyToolText


class WorkOrderQueryResponse(ToolResponse):
    """Typed work-order evidence, including a graceful not-found outcome."""

    work_order_id: NonEmptyToolText
    status: str | None = Field(
        default=None,
        description=(
            "The source status value only; it does not establish progression, "
            "normality, or a remediation outcome."
        ),
    )
    current_node: str | None = Field(
        default=None,
        description="The workflow node reported by the source system.",
    )
    current_handler: str | None = Field(
        default=None,
        description="The handler identifier reported by the source system.",
    )
    waiting_hours: float | None = Field(
        default=None,
        ge=0,
        description=(
            "Elapsed waiting duration reported by the source; without a "
            "separate SLA or threshold, it is not an on-time, late, or "
            "timeout judgment."
        ),
    )
    abnormal: bool | None = Field(
        default=None,
        description=(
            "The source anomaly flag only; false means the source flag is "
            "false and does not prove that the process is normal or has no "
            "other issue."
        ),
    )


class PermissionQueryRequest(ToolRequest):
    """Request for one user's permissions in one system."""

    user_id: NonEmptyToolText
    system_id: NonEmptyToolText


class PermissionQueryResponse(ToolResponse):
    """Typed permission facts without entitlement or policy conclusions."""

    user_id: NonEmptyToolText
    system_id: NonEmptyToolText
    roles: list[str] = Field(
        default_factory=list,
        description=(
            "Role identifiers returned by the source; no entitlement conclusion."
        ),
    )
    permissions: list[str] = Field(
        default_factory=list,
        description=(
            "Permission identifiers returned by the source; no policy conclusion."
        ),
    )
    missing_permissions: list[str] = Field(
        default_factory=list,
        description=(
            "Missing permission identifiers returned by the source; this "
            "does not establish cause or authorize a grant."
        ),
    )


class IncidentQueryRequest(ToolRequest):
    """Request for an incident snapshot by system and/or scope.

    ``site``, ``site_id`` and ``scope`` are intentionally separate typed
    fields.  They let a model pass the entity it extracted without the Python
    harness deciding which kind of outage the user meant.
    """

    system_id: str | None = None
    site: str | None = None
    site_id: str | None = None
    scope: str | None = None

    @model_validator(mode="after")
    def require_query_scope(self) -> IncidentQueryRequest:
        if not any(
            value and value.strip()
            for value in (self.system_id, self.site, self.site_id, self.scope)
        ):
            raise ValueError("at least one incident query scope is required")
        return self


class IncidentQueryResponse(ToolResponse):
    """Typed incident facts, with no implied remediation action."""

    system_id: str | None = None
    site: str | None = None
    site_id: str | None = None
    scope: str | None = None
    incident_id: str | None = None
    incident_status: str | None = Field(
        default=None,
        description="The incident status value reported by the source system.",
    )
    impact: str | None = Field(
        default=None,
        description=(
            "Impact text reported by the source system; no remediation conclusion."
        ),
    )


class ToolExecutionSummary(StateModel):
    """Small transient envelope passed from execution to result review."""

    tool_name: NonEmptyToolText
    status: Literal["completed", "not_found", "insufficient_evidence", "failed"]
    output: ToolResponse | None = None
    error_code: str | None = None


__all__ = [
    "IncidentQueryRequest",
    "IncidentQueryResponse",
    "PermissionQueryRequest",
    "PermissionQueryResponse",
    "ToolExecutionSummary",
    "ToolFieldPresentation",
    "ToolFieldValueKind",
    "ToolMode",
    "ToolRequest",
    "ToolResponse",
    "ToolResultStatus",
    "WorkOrderQueryRequest",
    "WorkOrderQueryResponse",
]
