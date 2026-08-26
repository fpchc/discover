"""LangGraph 状态机构建（graph-runtime-spec §2 拓扑）。

拓扑极简：两级解析 + 推理循环 + 工具执行。新增智能体不改图。
条件边：resolve_assistant 为 expert → resolve_skill，否则 → generic_chat；
agent 有工具调用 → tool_node，否则 → finish。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.catalog.models import TargetType
from app.runtime.state import GraphState

if TYPE_CHECKING:
    from app.runtime.runner import Runtime


def build_graph(runtime: Runtime) -> CompiledStateGraph[GraphState]:
    """构建并编译运行时图。节点方法由 Runtime 提供（每会话一份）。"""
    graph = StateGraph(GraphState)
    graph.add_node("resolve_assistant", runtime.resolve_assistant)
    graph.add_node("resolve_skill", runtime.resolve_skill)
    graph.add_node("assemble", runtime.assemble)
    graph.add_node("agent", runtime.agent)
    graph.add_node("tool_node", runtime.tool_node)
    graph.add_node("generic_chat", runtime.generic_chat)
    graph.add_node("finish", runtime.finish)

    graph.add_edge(START, "resolve_assistant")
    graph.add_conditional_edges(
        "resolve_assistant",
        route_from_resolve_assistant,
        {"resolve_skill": "resolve_skill", "generic_chat": "generic_chat"},
    )
    graph.add_edge("resolve_skill", "assemble")
    graph.add_edge("assemble", "agent")
    graph.add_conditional_edges(
        "agent",
        route_from_agent,
        {"tool_node": "tool_node", "finish": "finish"},
    )
    graph.add_edge("tool_node", "agent")
    graph.add_edge("generic_chat", "finish")
    graph.add_edge("finish", END)
    return graph.compile()


def route_from_resolve_assistant(state: GraphState) -> str:
    """resolve_assistant 后置：expert 目标走技能解析，否则通用对话。"""
    if state.active_target is not None and state.active_target.type == TargetType.EXPERT:
        return "resolve_skill"
    return "generic_chat"


def route_from_agent(state: GraphState) -> str:
    """推理后置（§2 边表）：无工具调用收尾，否则直接执行工具。"""
    return "tool_node" if state.pending_calls else "finish"
