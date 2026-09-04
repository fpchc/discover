"""Bounded ReAct 子图拓扑（react-runtime-v2-architecture §10）。

单一动机：把 BoundedReActExecutor 的节点方法按 §10 拓扑接成 LangGraph 子图。
Workflow 控制存在于 LangGraph（节点 + 条件边），禁止把流程控制写成自然语言提示词
（CLAUDE.md §1）。循环边界由 check_budget / evaluate_progress 的条件边保证：
预算软/硬超限、无进展、格式修复耗尽均路由到 finalize，绝不无限循环。
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.runtime.react.decision import AgentDecisionType
from app.runtime.react.executor import BoundedReActExecutor, ReactGraphState


def build_react_subgraph(
    executor: BoundedReActExecutor,
) -> CompiledStateGraph[ReactGraphState]:
    """构建并编译 Bounded ReAct 子图（§10 拓扑）。"""
    graph = StateGraph(ReactGraphState)
    graph.add_node("react_prepare", executor.react_prepare)
    graph.add_node("check_budget", executor.check_budget)
    graph.add_node("call_llm", executor.call_llm)
    graph.add_node("parse_decision", executor.parse_decision)
    graph.add_node("validate_decision", executor.validate_decision)
    graph.add_node("preflight_action", executor.preflight_action)
    graph.add_node("execute_tool", executor.execute_tool)
    graph.add_node("normalize_observation", executor.normalize_observation)
    graph.add_node("evaluate_progress", executor.evaluate_progress)
    graph.add_node("phase_contract", executor.phase_contract)
    graph.add_node("output_contract", executor.output_contract)
    graph.add_node("finalize", executor.finalize)

    graph.add_edge(START, "react_prepare")
    graph.add_edge("react_prepare", "check_budget")
    graph.add_conditional_edges(
        "check_budget",
        route_from_budget,
        {"call_llm": "call_llm", "finalize": "finalize"},
    )
    graph.add_edge("call_llm", "parse_decision")
    graph.add_edge("parse_decision", "validate_decision")
    graph.add_conditional_edges(
        "validate_decision",
        route_from_validate,
        {
            "preflight_action": "preflight_action",
            "phase_contract": "phase_contract",
            "output_contract": "output_contract",
            "finalize": "finalize",
            "call_llm": "call_llm",
        },
    )
    graph.add_edge("preflight_action", "execute_tool")
    graph.add_edge("execute_tool", "normalize_observation")
    graph.add_edge("normalize_observation", "evaluate_progress")
    graph.add_conditional_edges(
        "evaluate_progress",
        route_from_evaluate,
        {"check_budget": "check_budget", "finalize": "finalize"},
    )
    graph.add_edge("phase_contract", END)
    graph.add_edge("output_contract", END)
    graph.add_edge("finalize", END)
    return graph.compile()


def route_from_budget(state: ReactGraphState) -> str:
    """预算检查后路由：已触发终止（软/硬预算）→ finalize，否则 → call_llm。"""
    return "finalize" if state.terminate_reason else "call_llm"


def route_from_validate(state: ReactGraphState) -> str:
    """决策校验后路由（§10.1）：控制工具映射到对应 Contract/Finalize 节点。"""
    if state.terminate_reason == "format_repair":
        return "call_llm"
    if state.terminate_reason:
        return "finalize"
    decision = state.decision
    if decision is None:
        return "finalize"
    mapping = {
        AgentDecisionType.CALL_TOOLS: "preflight_action",
        AgentDecisionType.COMPLETE_PHASE: "phase_contract",
        AgentDecisionType.FINAL_ANSWER: "output_contract",
        AgentDecisionType.NEED_CLARIFICATION: "finalize",
        AgentDecisionType.INVALID_DECISION: "finalize",
    }
    return mapping.get(decision.decision_type, "finalize")


def route_from_evaluate(state: ReactGraphState) -> str:
    """进展判定后路由：no_progress → finalize（部分总结），否则回预算检查继续循环。"""
    return "finalize" if state.terminate_reason else "check_budget"
