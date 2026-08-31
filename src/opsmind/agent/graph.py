"""Minimal LangGraph orchestration for one OpsMind Agent run."""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from opsmind.agent.nodes import decide_action, understand_request
from opsmind.models import ModelGateway
from opsmind.state import OpsAgentState

OpsGraph = CompiledStateGraph[OpsAgentState, None, OpsAgentState, OpsAgentState]


def build_ops_graph(gateway: ModelGateway) -> OpsGraph:
    """Build the dependency-injected ``START → understand → decide → END`` graph."""

    builder = StateGraph(OpsAgentState)

    async def understand_node(state: OpsAgentState) -> dict[str, Any]:
        return await understand_request(state, gateway)

    async def decide_node(state: OpsAgentState) -> dict[str, Any]:
        return await decide_action(state, gateway)

    builder.add_node("understand_request", understand_node)
    builder.add_node("decide_action", decide_node)
    builder.add_edge(START, "understand_request")
    builder.add_edge("understand_request", "decide_action")
    builder.add_edge("decide_action", END)
    return builder.compile()


async def run_ops_agent(
    state: OpsAgentState,
    gateway: ModelGateway,
) -> OpsAgentState:
    """Run one graph invocation and return a validated canonical state."""

    canonical_state = OpsAgentState.model_validate(state)
    graph = build_ops_graph(gateway)
    result = await graph.ainvoke(canonical_state.model_copy(deep=True))
    return OpsAgentState.model_validate(result)
