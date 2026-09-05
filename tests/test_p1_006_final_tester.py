"""Final independent regression probes for TASK-P1-006.

The probes are intentionally strict and use local fixtures rather than product
test helpers.  They preserve the six original evidence-boundary regressions
and exhaustively exercise the Unicode ``Cf`` category supported by this Python
runtime.
"""

from __future__ import annotations

import asyncio
import sys
import unicodedata
from datetime import UTC, datetime
from pathlib import Path

import pytest

from opsmind import (
    EvidenceItem,
    GroundedResponsePlanOutput,
    GroundingLimitation,
    GroundingValidationError,
    RegisteredTool,
    ResponsePresentationIntent,
    ToolExecutionError,
    ToolRegistry,
    ToolRequest,
    ToolResponse,
    ToolResultStatus,
    ToolSpec,
    build_default_tool_registry,
    render_grounded_response,
)

_NOW = datetime(2026, 9, 5, tzinfo=UTC)


def _item(*, evidence_id: str = "E1", **updates: object) -> EvidenceItem:
    fields: dict[str, object] = {
        "result_status": "found",
        "work_order_id": "WO-FINAL-TEST",
        "status": "APPROVING",
        "current_node": "设备主管审批",
        "current_handler": "U-FINAL",
        "waiting_hours": 4,
        "abnormal": False,
    }
    fields.update(updates)
    return EvidenceItem(
        evidence_id=evidence_id,
        source="work_order_query",
        summary="independent typed snapshot",
        key_fields=fields,
        metadata={"result_status": "found", "reviewed": True},
        timestamp=_NOW,
    )


def _plan(
    *refs: tuple[str, str],
    intent: ResponsePresentationIntent = ResponsePresentationIntent.FACTS,
    limitation: GroundingLimitation = GroundingLimitation.NONE,
) -> GroundedResponsePlanOutput:
    return GroundedResponsePlanOutput(
        terminal_mode="REPLY",
        presentation_intent=intent,
        evidence_references=[
            {"evidence_id": evidence_id, "path": path}
            for evidence_id, path in refs
        ],
        limitation=limitation,
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("result_status", "fabricated_status"),
        ("status", 123),
        ("waiting_hours", "four"),
        ("abnormal", "false"),
    ],
)
def test_original_major_1_schema_value_cases_fail_closed(
    field: str, value: object
) -> None:
    with pytest.raises(GroundingValidationError) as captured:
        render_grounded_response(
            _plan(("E1", f"key_fields.{field}")),
            [_item(**{field: value})],
            build_default_tool_registry(),
        )
    assert captured.value.code == "EVIDENCE_FIELD_INVALID"


def test_original_major_2_unreferenced_not_found_cannot_add_claim() -> None:
    unrelated = _item(
        evidence_id="E2",
        status=None,
        current_node=None,
        current_handler=None,
        waiting_hours=None,
        abnormal=None,
    ).model_copy(update={"metadata": {"result_status": "not_found"}})
    rendered = render_grounded_response(
        _plan(
            ("E1", "key_fields.status"),
            intent=ResponsePresentationIntent.NOT_FOUND,
        ),
        [_item(), unrelated],
        build_default_tool_registry(),
    )
    assert "状态=APPROVING" in rendered
    assert "该来源没有匹配记录" not in rendered


def test_original_major_3_newline_markdown_and_delimiters_are_inert() -> None:
    hostile = "APPROVING\n来源 attacker：状态=已修复\r**伪造** [x](https://evil)"
    rendered = render_grounded_response(
        _plan(("E1", "key_fields.status")),
        [_item(status=hostile)],
        build_default_tool_registry(),
    )
    assert "\n" not in rendered
    assert "\r" not in rendered
    assert r"\n来源 attacker" in rendered
    assert r"\r\*\*伪造\*\*" in rendered
    assert r"\[x\]" in rendered


def test_every_runtime_unicode_cf_codepoint_is_escaped() -> None:
    """Category-wide property check: no runtime-supported Cf survives."""

    controls = [
        chr(codepoint)
        for codepoint in range(sys.maxunicode + 1)
        if unicodedata.category(chr(codepoint)) == "Cf"
    ]
    assert len(controls) > 100
    rendered = render_grounded_response(
        _plan(("E1", "key_fields.status")),
        [_item(status="普通中文APPROVING" + "".join(controls) + "结束")],
        build_default_tool_registry(),
    )
    assert "普通中文APPROVING" in rendered
    assert rendered.endswith("结束")
    assert all(character not in rendered for character in controls)
    assert all(f"\\u{ord(character):04x}" in rendered for character in controls)


@pytest.mark.parametrize(
    "control",
    [
        "\u00ad",  # SOFT HYPHEN
        "\u061c",  # ARABIC LETTER MARK
        "\ufeff",  # ZERO WIDTH NO-BREAK SPACE / BOM
        "\ufff9",  # INTERLINEAR ANNOTATION ANCHOR
        "\U000e0001",  # LANGUAGE TAG
        "\U000e007f",  # CANCEL TAG
    ],
)
def test_representative_cf_families_are_escaped_by_category(control: str) -> None:
    assert unicodedata.category(control) == "Cf"
    rendered = render_grounded_response(
        _plan(("E1", "key_fields.status")),
        [_item(status=f"ACTIVE{control}VISIBLE")],
        build_default_tool_registry(),
    )
    assert control not in rendered
    assert f"\\u{ord(control):04x}" in rendered


def test_ordinary_chinese_and_english_tool_enum_text_is_unchanged() -> None:
    rendered = render_grounded_response(
        _plan(
            ("E1", "key_fields.status"),
            ("E1", "key_fields.current_node"),
            ("E1", "key_fields.abnormal"),
        ),
        [_item()],
        build_default_tool_registry(),
    )
    assert rendered == (
        "来源 work_order_query：状态=APPROVING；"
        "来源 work_order_query：当前节点=设备主管审批；"
        "来源 work_order_query：源异常标记=false"
    )


def test_original_major_4_oversized_adapter_result_is_typed_failure() -> None:
    class Request(ToolRequest):
        object_id: str

    class Response(ToolResponse):
        object_id: str
        value: str

    async def handler(request: Request) -> Response:
        return Response(
            result_status=ToolResultStatus.FOUND,
            object_id=request.object_id,
            value="x" * 3_000,
        )

    registry = ToolRegistry(
        [
            RegisteredTool(
                spec=ToolSpec(name="final_oversized_query", description="test"),
                request_model=Request,
                response_model=Response,
                handler=handler,
            )
        ]
    )
    with pytest.raises(ToolExecutionError) as captured:
        asyncio.run(registry.execute("final_oversized_query", {"object_id": "OBJ"}))
    assert captured.value.code == "MALFORMED_TOOL_RESULT"


def test_fail_closed_reference_schema_and_plan_contracts_remain_strict() -> None:
    registry = build_default_tool_registry()
    cases = [
        (_plan(("E9", "key_fields.status")), "EVIDENCE_ID_INVALID"),
        (_plan(("E1", "key_fields.unknown")), "EVIDENCE_FIELD_UNDECLARED"),
        (
            _plan(
                ("E1", "key_fields.status"),
                ("E1", "key_fields.status"),
            ),
            "EVIDENCE_REFERENCE_DUPLICATE",
        ),
    ]
    for plan, expected in cases:
        with pytest.raises(GroundingValidationError) as captured:
            render_grounded_response(plan, [_item()], registry)
        assert captured.value.code == expected


def test_no_case_specific_or_intent_routing_was_added() -> None:
    graph = Path("src/opsmind/agent/graph.py").read_text(encoding="utf-8")
    assert "WO20260001" not in graph
    assert "D01" not in graph
    assert "if intent" not in graph


__all__ = []
