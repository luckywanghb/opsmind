from __future__ import annotations

import os

import pytest

from opsmind.agent import run_ops_agent
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

    result = await run_ops_agent(initial, gateway)

    assert result.understanding.primary_intent is not None
    assert result.understanding.request_type is not None
    assert result.decision.action is not None
    assert result.decision.goal is not None and result.decision.goal.strip()
    assert result.decision.rationale is not None and result.decision.rationale.strip()
