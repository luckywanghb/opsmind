from __future__ import annotations

import os

import pytest

from opsmind.agent import run_ops_agent_with_trace
from opsmind.models import DeepSeekSettings, build_deepseek_gateway
from opsmind.state import ConversationState, OpsAgentState


@pytest.mark.live
@pytest.mark.skipif(
    not os.getenv("DEEPSEEK_API_KEY", "").strip(),
    reason="DEEPSEEK_API_KEY is not configured",
)
@pytest.mark.asyncio
async def test_real_deepseek_kernel_smoke() -> None:
    settings = DeepSeekSettings.from_env()
    gateway = build_deepseek_gateway(settings)
    initial = OpsAgentState(
        conversation=ConversationState(current_query="WO20260001为什么一直没处理？")
    )

    result, events = await run_ops_agent_with_trace(initial, gateway)

    assert result.understanding.primary_intent is not None
    assert result.understanding.request_type is not None
    assert any(event.node == "decide_action" for event in events)
    assert result.tool.selected_tool == "work_order_query"
    assert result.tool.arguments == {"work_order_id": "WO20260001"}
    assert any(event.node == "review_tool_result" for event in events)
    assert any(event.node == "generate_response" for event in events)
    assert result.response.message is not None and result.response.message.strip()
    assert any(
        "\u4e00" <= character <= "\u9fff"
        for character in result.response.message
    )
