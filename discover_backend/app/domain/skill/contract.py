"""技能包运行时对齐契约（单阶段 Bounded ReAct 边界）。

本模块把「Claude Code 式技能包」与当前 Agent Runtime 的边界规则固化为纯函数：
Skill Pack 内容层只声明语义；流程控制、工具提供方与预算由 Runtime 承担。

规则来源：
- specs/agent-package-spec.md
- specs/skill-assembly-spec.md
- app/harness/react/decision.py 保留控制工具
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from pydantic import BaseModel, Field

# 与 app/harness/react/decision.py 保留命名空间一致；domain 不反向依赖 runtime，
# 因此在此固定一份。若控制工具集合变化，本常量与 runtime 必须同步修改。
TERMINAL_CONTROL_TOOLS: frozenset[str] = frozenset(
    {"submit_final_answer", "complete_phase", "request_clarification"}
)
FINAL_SUBMIT_TOOLS: frozenset[str] = frozenset({"submit_final_answer", "complete_phase"})


class ContractViolation(BaseModel):
    """技能包契约违例：可定位、可测试，不直接阻断加载。"""

    location: str
    rule: str
    message: str = Field(default="", description="面向维护者的修复说明")


def _mcp_tool_pattern(server_ids: Iterable[str]) -> re.Pattern[str] | None:
    """匹配正文中硬编码的 ``<server>.<tool>`` 引用。"""
    ids = sorted({str(server_id) for server_id in server_ids})
    if not ids:
        return None
    alternatives = "|".join(re.escape(server_id) for server_id in ids)
    return re.compile(rf"\b(?:{alternatives})\.", re.IGNORECASE)


def _contains_control_tool(body: str, names: frozenset[str]) -> str | None:
    lowered = body.lower()
    for name in names:
        if name in lowered:
            return name
    return None


def check_agent_manifest(
    *,
    agent_id: str,
    body: str,
    mcp_server_ids: Iterable[str],
) -> list[ContractViolation]:
    """校验 AGENT.md 正文是否越界承担技能级 / 工具级职责。"""
    violations: list[ContractViolation] = []
    pattern = _mcp_tool_pattern(mcp_server_ids)
    if pattern is not None:
        matches = sorted(set(pattern.findall(body)))
        if matches:
            violations.append(
                ContractViolation(
                    location=f"agents/{agent_id}/AGENT.md",
                    rule="agent_body_mcp_tool_ref",
                    message=(
                        "AGENT 正文不得硬编码具体 MCP 工具；工具提供方由能力依赖决定："
                        + ", ".join(matches)
                    ),
                )
            )
    control = _contains_control_tool(body, TERMINAL_CONTROL_TOOLS)
    if control is not None:
        violations.append(
            ContractViolation(
                location=f"agents/{agent_id}/AGENT.md",
                rule="agent_body_control_tool",
                message=(
                    f"AGENT 正文不得出现保留控制工具 {control!r}；"
                    "最终提交契约应放在 SKILL.md 正文。"
                ),
            )
        )
    return violations


def check_skill_manifest(
    *,
    agent_id: str,
    skill_id: str,
    body: str,
    mcp_server_ids: Iterable[str],
) -> list[ContractViolation]:
    """校验 SKILL.md 正文是否满足当前单阶段 ReAct 的最小契约。"""
    violations: list[ContractViolation] = []
    location = f"agents/{agent_id}/{skill_id}/SKILL.md"
    pattern = _mcp_tool_pattern(mcp_server_ids)
    if pattern is not None:
        matches = sorted(set(pattern.findall(body)))
        if matches:
            violations.append(
                ContractViolation(
                    location=location,
                    rule="skill_body_mcp_tool_ref",
                    message=(
                        "SKILL 正文不得硬编码具体 MCP 工具；"
                        "应描述能力语义（如企业工商能力 / 联网搜索能力）：" + ", ".join(matches)
                    ),
                )
            )
    if _contains_control_tool(body, FINAL_SUBMIT_TOOLS) is None:
        violations.append(
            ContractViolation(
                location=location,
                rule="skill_body_terminal_contract_missing",
                message=(
                    "SKILL 正文必须声明最终提交契约；"
                    "当前单阶段 ReAct 至少应包含 submit_final_answer 或 complete_phase。"
                ),
            )
        )
    return violations


def check_agent_dir(
    *,
    agent_id: str,
    agent_body: str,
    skills: Iterable[tuple[str, str]],
    mcp_server_ids: Iterable[str],
) -> list[ContractViolation]:
    """校验一个完整 agent 包（AGENT + 所有 SKILL）的边界契约。"""
    violations = check_agent_manifest(
        agent_id=agent_id, body=agent_body, mcp_server_ids=mcp_server_ids
    )
    for skill_id, skill_body in skills:
        violations.extend(
            check_skill_manifest(
                agent_id=agent_id,
                skill_id=skill_id,
                body=skill_body,
                mcp_server_ids=mcp_server_ids,
            )
        )
    return violations
