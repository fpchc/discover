"""技能包运行时对齐边界测试。

不发起真实网络 / DB。用真实 ``agents/`` 目录与真实 MCP 注册表验证：
每个 Agent 包必须满足当前单阶段 Bounded ReAct 的内容边界。
"""

from __future__ import annotations

from pathlib import Path

from app.config.loader import load_mcp_servers
from app.config.settings import Settings
from app.domain.skill.contract import (
    check_agent_dir,
    check_agent_manifest,
    check_skill_manifest,
)
from app.domain.skill.registry import AgentRegistry

ROOT = Path(__file__).resolve().parents[2]
AGENTS_DIR = ROOT / "agents"
MCP_REGISTRY_PATH = ROOT / "config" / "mcp-servers.yaml"


def test_agent_body_rejects_mcp_tool_reference() -> None:
    violations = check_agent_manifest(
        agent_id="finder",
        body="请调用 tyc_mcp.get_company_basic_profile",
        mcp_server_ids={"tyc_mcp"},
    )
    assert [v.rule for v in violations] == ["agent_body_mcp_tool_ref"]


def test_agent_body_rejects_control_tool() -> None:
    violations = check_agent_manifest(
        agent_id="finder", body="完成后调用 submit_final_answer", mcp_server_ids=set()
    )
    assert any(v.rule == "agent_body_control_tool" for v in violations)


def test_skill_body_requires_terminal_contract() -> None:
    violations = check_skill_manifest(
        agent_id="finder",
        skill_id="research",
        body="先采集，再写报告。",
        mcp_server_ids=set(),
    )
    assert any(v.rule == "skill_body_terminal_contract_missing" for v in violations)


def test_skill_body_rejects_mcp_tool_reference() -> None:
    violations = check_skill_manifest(
        agent_id="finder",
        skill_id="research",
        body="先调用 tyc_mcp.get_company_basic_profile，再 submit_final_answer",
        mcp_server_ids={"tyc_mcp"},
    )
    assert any(v.rule == "skill_body_mcp_tool_ref" for v in violations)


async def test_real_agents_pass_runtime_alignment() -> None:
    mcp_registry = await load_mcp_servers(MCP_REGISTRY_PATH)
    server_ids = {server.id for server in mcp_registry.servers}
    registry = AgentRegistry(Settings(_env_file=None, agents_root_dir=AGENTS_DIR), mcp_registry)
    snapshot = await registry.refresh()
    assert snapshot.failures == [], [failure.model_dump() for failure in snapshot.failures]

    violations = []
    for agent_id, package in snapshot.packages.items():
        assert package.skill_failures == [], [
            failure.model_dump() for failure in package.skill_failures
        ]
        violations.extend(
            check_agent_dir(
                agent_id=agent_id,
                agent_body=package.manifest.body,
                skills=((skill_id, skill.body) for skill_id, skill in package.skills.items()),
                mcp_server_ids=server_ids,
            )
        )

    assert violations == [], [violation.model_dump() for violation in violations]


async def test_preloaded_documents_injected_into_assembly_prompt() -> None:
    """render 阶段依赖的模板/证据规则在装配期预加载，保证可见输出符合 card-format。"""
    mcp_registry = await load_mcp_servers(MCP_REGISTRY_PATH)
    registry = AgentRegistry(Settings(_env_file=None, agents_root_dir=AGENTS_DIR), mcp_registry)
    await registry.refresh()
    plan = registry.assemble("discover-new", "client-finder")
    assert "预加载参考文档" in plan.system_prompt
    assert "三段式结构" in plan.system_prompt
    assert "证据等级" in plan.system_prompt
