"""Developer tests for strict loop-state numeric boundaries."""

import math

import pytest
from pydantic import ValidationError

from opsmind import OpsAgentState


@pytest.mark.parametrize(
    "loop",
    [
        {"round_count": "1"},
        {"tool_call_count": True},
        {"max_rounds": "2"},
        {"max_tool_calls": 1.5},
        {"tool_timeout_seconds": "30.0"},
    ],
)
def test_loop_numbers_reject_coercive_values(loop: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        OpsAgentState(loop=loop)


@pytest.mark.parametrize("timeout", [math.inf, -math.inf, math.nan])
def test_tool_timeout_rejects_non_finite_values(timeout: float) -> None:
    with pytest.raises(ValidationError):
        OpsAgentState(loop={"tool_timeout_seconds": timeout})


def test_loop_numbers_accept_exact_finite_numeric_types() -> None:
    state = OpsAgentState(
        loop={
            "round_count": 1,
            "tool_call_count": 2,
            "retry_count": 0,
            "max_rounds": 4,
            "max_tool_calls": 6,
            "max_retries": 2,
            "tool_timeout_seconds": 15.5,
        }
    )

    assert state.loop.round_count == 1
    assert state.loop.tool_timeout_seconds == 15.5
