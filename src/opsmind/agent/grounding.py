"""Deterministic evidence-reference validation and grounded rendering.

The model is allowed to choose *which* compact evidence fields matter.  It is
not allowed to supply a factual sentence.  This module is the hard boundary:
references are resolved against the run-local typed tool contracts and every
user-facing value is rendered from the resolved source field.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import cast
from unicodedata import category

from pydantic import JsonValue, ValidationError

from opsmind.agent.errors import AgentError
from opsmind.agent.schemas import (
    ClarificationTarget,
    EvidenceReference,
    GroundedResponsePlanOutput,
    GroundedTerminalMode,
    GroundingLimitation,
    ResponsePresentationIntent,
)
from opsmind.state import EvidenceItem
from opsmind.tools import (
    ToolFieldPresentation,
    ToolRegistry,
    UnknownToolError,
    UnknownToolFieldError,
)


class GroundingValidationError(AgentError):
    """A response plan cannot be proven to reference available evidence."""

    def __init__(self, code: str = "GROUNDING_REFERENCE_INVALID") -> None:
        # Keep errors safe for API boundaries: the offending value/path may
        # contain provider or user data and is therefore never included.
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class ResolvedEvidenceReference:
    """One validated plan reference and its typed source value."""

    reference: EvidenceReference
    item: EvidenceItem
    field_name: str
    value: JsonValue
    presentation: ToolFieldPresentation


_EVIDENCE_ID = re.compile(r"^E[1-9][0-9]{0,5}$")
_PATH_TOKEN = re.compile(r"^(?:[A-Za-z_][A-Za-z0-9_-]*|[0-9]+)$")
_ROOT_FIELDS = frozenset({"key_fields", "metadata"})
_LIMITED_PRESENTATIONS = frozenset(
    {
        ResponsePresentationIntent.FACTS_WITH_LIMITATION,
        ResponsePresentationIntent.LIMITED_FACTS,
    }
)


def stable_evidence_items(items: Iterable[EvidenceItem]) -> list[EvidenceItem]:
    """Return detached evidence with deterministic IDs for one run.

    Existing IDs are preserved.  Missing/duplicate IDs are assigned in list
    order, which makes references stable for a run while keeping caller-owned
    state immutable.
    """

    parsed_items: list[EvidenceItem] = []
    explicit_counts: dict[str, int] = {}
    for raw_item in items:
        try:
            item = EvidenceItem.model_validate(raw_item)
        except ValidationError as exc:
            raise GroundingValidationError("EVIDENCE_ITEM_INVALID") from exc
        if item.evidence_id is not None:
            if not _EVIDENCE_ID.fullmatch(item.evidence_id):
                raise GroundingValidationError("EVIDENCE_ID_INVALID")
            explicit_counts[item.evidence_id] = (
                explicit_counts.get(item.evidence_id, 0) + 1
            )
        parsed_items.append(item)

    # A missing ID must not consume a valid explicit ID that occurs later in
    # the same run. Unique caller-supplied IDs are therefore reserved first;
    # duplicate explicit IDs keep their first occurrence and are repaired
    # deterministically for subsequent occurrences.
    reserved = {
        evidence_id
        for evidence_id, count in explicit_counts.items()
        if count == 1
    }
    stable: list[EvidenceItem] = []
    used: set[str] = set()
    next_number = 1
    for item in parsed_items:
        evidence_id = item.evidence_id
        if evidence_id is None or evidence_id in used:
            while (
                f"E{next_number}" in used
                or f"E{next_number}" in reserved
            ):
                next_number += 1
            evidence_id = f"E{next_number}"
            next_number += 1
        used.add(evidence_id)
        stable.append(
            item.model_copy(deep=True, update={"evidence_id": evidence_id})
        )
    return stable


def _canonical_path(reference: EvidenceReference) -> tuple[str, list[str]]:
    """Parse a field path without allowing arbitrary object traversal."""

    path = reference.path
    # Accept the concise example form ``E1.status`` while retaining the
    # separate typed evidence_id as the authoritative identity.
    prefix = f"{reference.evidence_id}."
    if path.startswith(prefix):
        path = path[len(prefix) :]
    parts = path.split(".")
    if not parts or any(not _PATH_TOKEN.fullmatch(part) for part in parts):
        raise GroundingValidationError("EVIDENCE_PATH_INVALID")
    if parts[0] in _ROOT_FIELDS:
        if len(parts) < 2:
            raise GroundingValidationError("EVIDENCE_PATH_INVALID")
        return parts[0], parts[1:]
    # The short form is intentionally shorthand for a typed key field.  It
    # keeps prompts readable without introducing a separate routing grammar.
    return "key_fields", parts


def _nested_value(value: object, path: list[str]) -> JsonValue:
    current = value
    for part in path:
        if isinstance(current, dict):
            if part not in current:
                raise GroundingValidationError("EVIDENCE_FIELD_MISSING")
            current = current[part]
        elif isinstance(current, list) and part.isdigit():
            index = int(part)
            if index >= len(current):
                raise GroundingValidationError("EVIDENCE_FIELD_MISSING")
            current = current[index]
        else:
            raise GroundingValidationError("EVIDENCE_FIELD_MISSING")
    if isinstance(current, datetime):
        current = current.isoformat()
    if current is None:
        raise GroundingValidationError("EVIDENCE_FIELD_MISSING")
    if isinstance(current, float) and not math.isfinite(current):
        raise GroundingValidationError("EVIDENCE_FIELD_INVALID")
    if not isinstance(current, (str, int, float, bool, list, dict)):
        raise GroundingValidationError("EVIDENCE_FIELD_INVALID")
    return cast(JsonValue, current)


def _evidence_payload(item: EvidenceItem) -> dict[str, JsonValue]:
    """Build the detached typed response payload used for validation.

    ``result_status`` is retained in ``metadata`` for review bookkeeping by
    older evidence projections.  The typed response payload is therefore
    reconstructed from ``key_fields`` with that status only as a fallback;
    review-only metadata such as ``reviewed`` never enters the response
    contract.
    """

    payload = dict(item.key_fields)
    if "result_status" not in payload:
        status = item.metadata.get("result_status")
        if status is not None:
            payload["result_status"] = status
    elif "result_status" in item.metadata:
        # A duplicated status is only trustworthy when both projections agree.
        # Do this check here, before a selected metadata status can influence
        # NOT_FOUND rendering.
        if item.key_fields["result_status"] != item.metadata["result_status"]:
            raise GroundingValidationError("EVIDENCE_FIELD_INVALID")
    return payload


def validate_evidence_references(
    plan: GroundedResponsePlanOutput,
    evidence: Iterable[EvidenceItem],
    tool_registry: ToolRegistry,
    *,
    expected_terminal_mode: GroundedTerminalMode | str | None = None,
) -> tuple[ResolvedEvidenceReference, ...]:
    """Resolve and validate every plan reference, or fail closed.

    No partial result is returned.  A caller must not invoke the renderer
    unless this function has resolved all references successfully.
    """

    try:
        parsed_plan = GroundedResponsePlanOutput.model_validate(plan)
    except ValidationError as exc:
        raise GroundingValidationError("GROUNDING_PLAN_INVALID") from exc

    if expected_terminal_mode is not None:
        try:
            expected = GroundedTerminalMode(expected_terminal_mode)
        except ValueError as exc:
            raise GroundingValidationError("GROUNDING_TERMINAL_INVALID") from exc
        if parsed_plan.terminal_mode is not expected:
            raise GroundingValidationError("GROUNDING_TERMINAL_MISMATCH")

    stable = stable_evidence_items(evidence)
    by_id = {item.evidence_id: item for item in stable}
    resolved: list[ResolvedEvidenceReference] = []
    validated_payloads: dict[str, dict[str, object]] = {}
    seen: set[tuple[str, str]] = set()
    for reference in parsed_plan.evidence_references:
        if reference.evidence_id not in by_id:
            raise GroundingValidationError("EVIDENCE_ID_INVALID")
        root, path = _canonical_path(reference)
        key = (reference.evidence_id, f"{root}.{'/'.join(path)}")
        if key in seen:
            raise GroundingValidationError("EVIDENCE_REFERENCE_DUPLICATE")
        seen.add(key)
        item = by_id[reference.evidence_id]
        top_field = path[0]
        # Resolve the top-level declaration before touching the generic
        # evidence object so an unknown field is never confused with an absent
        # declared field. Nested declaration is enforced by the typed payload
        # and the bounded path grammar below.
        try:
            presentation = tool_registry.field_presentation(item.source, top_field)
        except (UnknownToolError, UnknownToolFieldError) as exc:
            raise GroundingValidationError("EVIDENCE_FIELD_UNDECLARED") from exc

        if root == "metadata":
            # ``result_status`` is duplicated in compact metadata for safe
            # review bookkeeping, but it remains declared by the typed tool
            # response and can therefore be referenced explicitly.  Other
            # harness metadata (such as ``reviewed``) is not source evidence.
            if top_field != "result_status" or len(path) != 1:
                raise GroundingValidationError("EVIDENCE_FIELD_UNDECLARED")
        if reference.evidence_id not in validated_payloads:
            try:
                validated_payloads[reference.evidence_id] = (
                    tool_registry.validate_response_payload(
                        item.source,
                        _evidence_payload(item),
                    )
                )
            except (UnknownToolError, UnknownToolFieldError) as exc:
                raise GroundingValidationError("EVIDENCE_FIELD_UNDECLARED") from exc
            except Exception as exc:
                # This intentionally includes Pydantic's ValidationError and
                # JSON encoding failures. The source payload is untrusted
                # state and must never be coerced into a factual value.
                raise GroundingValidationError("EVIDENCE_FIELD_INVALID") from exc

        # Resolve presence from the original root so a metadata fallback does
        # not make an absent ``key_fields.result_status`` appear referenceable.
        raw_root = item.key_fields if root == "key_fields" else item.metadata
        _nested_value(raw_root, path)
        try:
            value = _nested_value(validated_payloads[reference.evidence_id], path)
        except GroundingValidationError:
            # A declared nullable field is represented as null by Pydantic and
            # is intentionally reported as missing at the grounding boundary.
            raise
        resolved.append(
            ResolvedEvidenceReference(
                reference=reference,
                item=item,
                field_name=top_field,
                value=value,
                presentation=presentation,
            )
        )
    return tuple(resolved)


def _format_json_value(value: JsonValue, presentation: ToolFieldPresentation) -> str:
    """Format one source value without deriving business conclusions."""

    if isinstance(value, bool):
        # Keep source flags mechanically visible as true/false.  In
        # particular, false must never become a normality assertion.
        rendered = "true" if value else "false"
    elif isinstance(value, list):
        rendered_items: list[str] = []
        for item in value:
            if isinstance(item, bool):
                rendered_items.append("true" if item else "false")
            elif isinstance(item, (str, int, float)):
                rendered_items.append(str(item))
            else:
                rendered_items.append(
                    json.dumps(item, ensure_ascii=False, sort_keys=True)
                )
        rendered = "、".join(rendered_items) if rendered_items else "（空）"
    elif isinstance(value, dict):
        rendered = json.dumps(value, ensure_ascii=False, sort_keys=True)
    elif isinstance(value, float):
        rendered = str(int(value)) if value.is_integer() else str(value)
    else:
        rendered = str(value)
    unit = presentation.unit_zh or ""
    return f"{_escape_untrusted_text(rendered)}{_escape_untrusted_text(unit)}"


def _escape_untrusted_text(value: str) -> str:
    """Keep source-controlled strings inert in plain-text/Markdown clients."""

    escaped: list[str] = []
    underscore_count = value.count("_")
    for character in value:
        codepoint = ord(character)
        if character == "\n":
            escaped.append(r"\n")
        elif character == "\r":
            escaped.append(r"\r")
        elif (
            codepoint < 0x20
            or 0x7F <= codepoint <= 0x9F
            or codepoint in {0x2028, 0x2029}
            or category(character) == "Cf"
        ):
            escaped.append(f"\\u{codepoint:04x}")
        # Keep ordinary identifiers such as ``EQUIPMENT_VIEW`` unchanged;
        # paired underscores are escaped because they can form Markdown
        # emphasis even when supplied entirely by a source value.
        elif character == "_" and underscore_count >= 2:
            escaped.append(r"\_")
        elif character in r"\`*~#[]()<>!|;:=；：":
            escaped.append(f"\\{character}")
        else:
            escaped.append(character)
    return "".join(escaped)


def _limitation_text(
    limitation: GroundingLimitation,
    *,
    has_threshold: bool,
    has_cause: bool,
) -> str | None:
    """Map a typed limitation to a fixed Simplified-Chinese sentence."""

    if limitation is GroundingLimitation.NONE:
        return None
    if limitation in {
        GroundingLimitation.CAUSE_UNAVAILABLE,
        GroundingLimitation.MISSING_CAUSE,
    }:
        if has_cause:
            return None
        return "当前来源未提供原因字段，无法据此判断原因。"
    if limitation in {
        GroundingLimitation.THRESHOLD_UNAVAILABLE,
        GroundingLimitation.MISSING_THRESHOLD,
    }:
        if has_threshold:
            return None
        return "当前来源未提供 SLA 或阈值字段，无法据此判断是否超时或逾期。"
    return {
        GroundingLimitation.ENTITLEMENT_UNAVAILABLE: (
            "当前来源未提供应具备该权限的资格或授权依据，不能据此判断是否应当拥有权限。"
        ),
        GroundingLimitation.REMEDIATION_UNAVAILABLE: (
            "当前来源未提供修复或变更结果；本次只读运行未执行修改。"
        ),
        GroundingLimitation.MATCH_UNAVAILABLE: (
            "当前来源没有匹配记录，无法提供未返回的业务事实。"
        ),
        GroundingLimitation.SCOPE_UNAVAILABLE: (
            "当前来源未提供影响范围，无法据此判断范围。"
        ),
        GroundingLimitation.EVIDENCE_INSUFFICIENT: (
            "当前来源证据不足，无法得出未返回的业务结论。"
        ),
    }.get(limitation)


def render_grounded_response(
    plan: GroundedResponsePlanOutput,
    evidence: Iterable[EvidenceItem],
    tool_registry: ToolRegistry,
    *,
    expected_terminal_mode: GroundedTerminalMode | str | None = None,
) -> str:
    """Render a deterministic, source-qualified Simplified-Chinese reply.

    The renderer consumes only resolved typed values and bounded enum intent;
    review summaries, decision prose, query wording and model-generated text
    never reach the returned message.
    """

    try:
        parsed_plan = GroundedResponsePlanOutput.model_validate(plan)
    except ValidationError as exc:
        raise GroundingValidationError("GROUNDING_PLAN_INVALID") from exc
    evidence_items = list(evidence)
    resolved = validate_evidence_references(
        parsed_plan,
        evidence_items,
        tool_registry,
        expected_terminal_mode=expected_terminal_mode,
    )
    if parsed_plan.terminal_mode is GroundedTerminalMode.END_CONVERSATION:
        return ""

    parts: list[str] = []
    for reference in resolved:
        label = _escape_untrusted_text(reference.presentation.label_zh)
        value = _format_json_value(reference.value, reference.presentation)
        # The source name comes from the registered tool key (not provider
        # data); preserve its contract spelling for audit/UI consumers.
        parts.append(f"来源 {reference.item.source}：{label}={value}")

    if parsed_plan.presentation_intent is ResponsePresentationIntent.NOT_FOUND:
        # ``NOT_FOUND`` is a presentation of a typed adapter status, not a
        # model assertion.  Do not let a plan turn a found result into a
        # fabricated absence; with no typed not-found status, use the generic
        # limitation below instead.
        not_found = any(
            reference.field_name == "result_status"
            and reference.value == "not_found"
            for reference in resolved
        )
        if not_found:
            parts.append("该来源没有匹配记录，无法提供未返回的业务事实。")
        else:
            parts.append("当前没有可引用的来源字段，无法提供匹配记录之外的业务事实。")
    elif parsed_plan.presentation_intent in _LIMITED_PRESENTATIONS:
        semantics = {
            reference.presentation.semantic for reference in resolved
        }
        limitation = _limitation_text(
            parsed_plan.limitation,
            has_threshold=("threshold" in semantics or "sla" in semantics),
            has_cause=("cause" in semantics),
        )
        if limitation is None and parsed_plan.limitation is GroundingLimitation.NONE:
            limitation = (
                "当前来源未提供原因、SLA 或阈值字段，无法据此得出未返回的业务结论。"
            )
        if limitation:
            parts.append(limitation)
    elif parsed_plan.limitation is not GroundingLimitation.NONE:
        limitation = _limitation_text(
            parsed_plan.limitation,
            has_threshold=False,
            has_cause=False,
        )
        if limitation:
            parts.append(limitation)

    if parsed_plan.terminal_mode is GroundedTerminalMode.ASK_USER:
        clarification = {
            ClarificationTarget.GENERIC: "请补充一个可用于只读查询的对象标识或范围。",
            ClarificationTarget.IDENTIFIER: "请补充要查询的对象标识。",
            ClarificationTarget.USER_ID: "请补充用户标识。",
            ClarificationTarget.SYSTEM_ID: "请补充系统标识。",
            ClarificationTarget.SITE: "请补充站点。",
            ClarificationTarget.SCOPE: "请补充查询范围。",
        }[parsed_plan.clarification_target]
        parts.append(clarification)
    elif parsed_plan.terminal_mode is GroundedTerminalMode.TRANSFER_HUMAN:
        parts.append(
            "当前只能提供上述已引用来源字段；本次只读运行未执行修改，需要转人工处理。"
        )

    if not parts:
        return "当前没有可引用的来源字段，无法基于只读证据给出事实回复。"
    return "；".join(parts)


# Descriptive aliases keep the contract discoverable for callers that use
# “reply” rather than “response” in their naming.
render_grounded_reply = render_grounded_response
validate_grounded_response_plan = validate_evidence_references


__all__ = [
    "GroundingValidationError",
    "ResolvedEvidenceReference",
    "render_grounded_reply",
    "render_grounded_response",
    "stable_evidence_items",
    "validate_evidence_references",
    "validate_grounded_response_plan",
]
