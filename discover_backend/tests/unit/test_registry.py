"""Step 6 装配层测试。"""

from pathlib import Path

import pytest
import yaml
from app.config.loader import MCPRegistry, MCPServer, MCSCapability
from app.config.settings import Settings
from app.errors.base import RegistryValidationError
from app.registry.hot_reload import HotReloader
from app.registry.loader import AgentRegistrySnapshot
from app.registry.registry import AgentRegistry


def _agent_md(
    *,
    agent_id: str = "finder",
    default_skill: str | None = "research",
    skills: tuple[str, ...] = ("research",),
    body: str = "全局约束：语气专业，只讲事实。",
    **extra: object,
) -> str:
    header: dict[str, object] = {
        "agent_id": agent_id,
        "display_name": "客户发现",
        "version": "1.0.0",
        "description": "发现潜在客户",
        "scope": {"applies": "用户想找潜在客户时", "does_not_apply": "用户想写周报时"},
        "env_whitelist": ["FINDER_API_KEY"],
        "model_preference": "qwen-max",
        "skills": list(skills),
    }
    if default_skill:
        header["default_skill"] = default_skill
    header.update(extra)
    front = yaml.safe_dump(header, allow_unicode=True, sort_keys=False)
    return f"---\n{front}---\n{body}\n"


def _skill_md(**overrides: object) -> str:
    header: dict[str, object] = {
        "skill_id": "research",
        "version": "1.0.0",
        "description": "客户调研",
        "scope": {"applies": "需要调研目标公司时", "does_not_apply": "纯闲聊"},
        "keywords": ["客户", "调研"],
        "mcp_dependencies": [
            {"server": "alibaba_search", "core_tools": ["search", "search_news"], "required": True}
        ],
        "scripts": [
            {
                "path": "scripts/run_research.py",
                "name": "run_research",
                "description": "执行一次客户调研",
                "schema_path": "schemas/research.json",
            }
        ],
        "documents": [{"path": "references/client-intro.md", "when": "需要背景资料时"}],
        "gates": [
            {
                "id": "sources_collected",
                "condition": "至少收集 3 个独立信源",
                "validator": "scripts/check_sources.py",
                "schema_path": "schemas/gate_input.json",
            }
        ],
        "templates": [{"path": "templates/report.md", "purpose": "最终报告模板"}],
    }
    header.update(overrides)
    front = yaml.safe_dump(header, allow_unicode=True, sort_keys=False)
    return f"---\n{front}---\n完整工作流：先收集信源，再撰写报告。\n"


def _write_agent(
    root: Path,
    *,
    name: str = "finder",
    agent_md: str | None = None,
    skill_md: str | None = None,
    skill_dir: bool = True,
    files: bool = True,
    script_content: str = "print('ok')\n",
) -> None:
    agent_dir = root / name
    agent_dir.mkdir(parents=True)
    (agent_dir / "AGENT.md").write_text(agent_md or _agent_md(), encoding="utf-8")
    if skill_dir:
        sdir = agent_dir / "research"
        (sdir / "scripts").mkdir(parents=True)
        (sdir / "schemas").mkdir(parents=True)
        (sdir / "references").mkdir(parents=True)
        (sdir / "templates").mkdir(parents=True)
        (sdir / "SKILL.md").write_text(skill_md or _skill_md(), encoding="utf-8")
        if files:
            (sdir / "scripts" / "run_research.py").write_text(script_content, encoding="utf-8")
            (sdir / "scripts" / "check_sources.py").write_text("print('ok')\n", encoding="utf-8")
            (sdir / "schemas" / "research.json").write_text("{}", encoding="utf-8")
            (sdir / "schemas" / "gate_input.json").write_text("{}", encoding="utf-8")
            (sdir / "references" / "client-intro.md").write_text("# 背景\n", encoding="utf-8")
            (sdir / "templates" / "report.md").write_text("# 报告\n", encoding="utf-8")


def _mcp_registry(
    *server_ids: str,
    capabilities: dict[str, list[str]] | None = None,
) -> MCPRegistry:
    servers = [
        MCPServer(
            id=server_id,
            transport="streamable_http",
            base_url=f"https://{server_id}.example.com",
        )
        for server_id in server_ids
    ]
    caps = {name: MCSCapability(servers=sids) for name, sids in (capabilities or {}).items()}
    return MCPRegistry(servers=servers, capabilities=caps)


async def _build_registry(
    root: Path,
    *mcp_ids: str,
    capabilities: dict[str, list[str]] | None = None,
    **overrides: object,
) -> AgentRegistry:
    settings = Settings(_env_file=None, agents_root_dir=root, **overrides)
    registry = AgentRegistry(settings, _mcp_registry(*mcp_ids, capabilities=capabilities))
    await registry.refresh()
    return registry


async def _load(
    root: Path,
    *mcp_ids: str,
    capabilities: dict[str, list[str]] | None = None,
    **overrides: object,
) -> AgentRegistrySnapshot:
    registry = await _build_registry(root, *mcp_ids, capabilities=capabilities, **overrides)
    return registry.snapshot


# ---- 加载与校验 ----
async def test_relative_agents_root_resolved_absolute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """回归：相对 agents_root（生产默认 Path("agents")）须归一为绝对路径。

    否则 skill_dir / 脚本宿主路径保持相对，脚本 subprocess cwd=工作区时会把
    相对路径按工作区解析而找不到（实测 dedup_manager "No such file"）。
    """
    _write_agent(tmp_path / "agents")
    monkeypatch.chdir(tmp_path)
    registry = AgentRegistry(
        Settings(_env_file=None, agents_root_dir=Path("agents")), _mcp_registry("alibaba_search")
    )
    await registry.refresh()
    package = registry.get_agent("finder")
    assert package is not None
    assert package.root.is_absolute()
    assert (package.root / "research").is_dir()


async def test_load_valid_agent(tmp_path: Path) -> None:
    _write_agent(tmp_path)
    snapshot = await _load(tmp_path, "alibaba_search")
    assert len(snapshot.packages) == 1
    assert snapshot.failures == []
    package = snapshot.packages["finder"]
    assert package.manifest.agent_id == "finder"
    assert package.manifest.default_skill == "research"
    assert "research" in package.skills
    assert package.skill_failures == []


async def test_manifest_kind_type_defaults_to_agent_expert(tmp_path: Path) -> None:
    """未声明 kind/type 时默认 agent/expert（向后兼容既有清单）。"""
    _write_agent(tmp_path)
    snapshot = await _load(tmp_path, "alibaba_search")
    package = snapshot.packages["finder"]
    assert package.manifest.kind == "agent"
    assert package.manifest.type == "expert"


async def test_manifest_invalid_kind_or_type_rejected(tmp_path: Path) -> None:
    """kind/type 超出当前支持（skill 等）→ 该智能体判无效，不影响其他。"""
    for idx, extra in enumerate(({"kind": "skill"}, {"type": "basic"})):
        case_dir = tmp_path / f"case{idx}"
        case_dir.mkdir()
        _write_agent(case_dir, agent_md=_agent_md(**extra))
        snapshot = await _load(case_dir, "alibaba_search")
        assert snapshot.packages == {}
        assert snapshot.failures[0].agent_id == "finder"


async def test_reserved_generic_agent_id_rejected(tmp_path: Path) -> None:
    """保留字 generic 为通用对话默认态，专家包不得占用。"""
    _write_agent(tmp_path, name="generic", agent_md=_agent_md(agent_id="generic"))
    snapshot = await _load(tmp_path, "alibaba_search")
    assert snapshot.packages == {}
    assert "保留字" in snapshot.failures[0].reason


async def test_agent_id_must_equal_dir_name(tmp_path: Path) -> None:
    _write_agent(tmp_path, name="wrong")
    snapshot = await _load(tmp_path, "alibaba_search")
    assert snapshot.packages == {}
    assert snapshot.failures[0].agent_id == "wrong"
    assert "目录名" in snapshot.failures[0].reason


async def test_missing_skill_dir_marks_skill_invalid(tmp_path: Path) -> None:
    _write_agent(tmp_path, skill_dir=False)
    snapshot = await _load(tmp_path, "alibaba_search")
    package = snapshot.packages["finder"]
    assert package.skills == {}
    assert len(package.skill_failures) == 1
    assert package.skill_failures[0].skill_id == "research"


async def test_missing_script_file_marks_skill_invalid(tmp_path: Path) -> None:
    skill_md = _skill_md(
        scripts=[{"path": "scripts/ghost.py", "name": "ghost", "description": "x"}]
    )
    _write_agent(tmp_path, skill_md=skill_md)
    snapshot = await _load(tmp_path, "alibaba_search")
    package = snapshot.packages["finder"]
    assert "research" not in package.skills
    reason = package.skill_failures[0].invalid_reason
    assert reason is not None
    assert "脚本文件不存在" in reason


async def test_mcp_server_not_registered_marks_skill_invalid(tmp_path: Path) -> None:
    _write_agent(tmp_path)
    snapshot = await _load(tmp_path)  # 无任何 MCP 服务器
    package = snapshot.packages["finder"]
    assert "research" not in package.skills
    assert "MCP 服务器未注册" in package.skill_failures[0].invalid_reason


async def test_default_skill_not_in_index_fails_agent(tmp_path: Path) -> None:
    _write_agent(tmp_path, agent_md=_agent_md(default_skill="nope"))
    snapshot = await _load(tmp_path, "alibaba_search")
    assert snapshot.packages == {}
    assert "默认技能不在技能索引内" in snapshot.failures[0].reason


async def test_agent_body_budget_exceeded(tmp_path: Path) -> None:
    _write_agent(tmp_path, agent_md=_agent_md(body="x" * 100))
    snapshot = await _load(tmp_path, "alibaba_search", agent_body_max_chars=10)
    assert snapshot.packages == {}
    assert "正文超预算" in snapshot.failures[0].reason


async def test_duplicate_script_tool_name_marks_skill_invalid(tmp_path: Path) -> None:
    skill_md = _skill_md(
        scripts=[
            {"path": "scripts/run_research.py", "name": "run_research", "description": "a"},
            {"path": "scripts/run_research.py", "name": "run_research", "description": "b"},
        ]
    )
    _write_agent(tmp_path, skill_md=skill_md)
    snapshot = await _load(tmp_path, "alibaba_search")
    package = snapshot.packages["finder"]
    assert "research" not in package.skills
    assert "脚本工具名重复" in package.skill_failures[0].invalid_reason


async def test_missing_frontmatter_fails_agent(tmp_path: Path) -> None:
    agent_dir = tmp_path / "finder"
    agent_dir.mkdir()
    (agent_dir / "AGENT.md").write_text("# 没有 frontmatter\n", encoding="utf-8")
    snapshot = await _load(tmp_path, "alibaba_search")
    assert snapshot.packages == {}
    assert "frontmatter" in snapshot.failures[0].reason


# ---- 绝对路径禁令（§9） ----
async def test_absolute_path_literal_in_skill_script(tmp_path: Path) -> None:
    _write_agent(tmp_path, script_content='ROOT = "C:/evil/proj"\n')
    snapshot = await _load(tmp_path, "alibaba_search")
    package = snapshot.packages["finder"]
    assert "research" not in package.skills
    assert "绝对路径" in package.skill_failures[0].invalid_reason


# ---- 两级索引 ----
async def test_index_two_level_isolation(tmp_path: Path) -> None:
    _write_agent(tmp_path)
    registry = await _build_registry(tmp_path, "alibaba_search")
    index = registry.index()
    assert "finder" in index.agents
    entry = index.agents["finder"]
    assert entry.display_name == "客户发现"
    assert entry.default_skill == "research"
    assert "research" in index.skills_by_agent["finder"]
    skill = index.skills_by_agent["finder"]["research"]
    assert skill.keywords == ["客户", "调研"]
    assert skill.scope.applies == "需要调研目标公司时"
    # 一级索引不含技能细节
    dumped = index.agents["finder"].model_dump()
    assert "skills" not in dumped
    assert "skill_id" not in dumped


# ---- 技能装配 ----
async def test_assemble_plan(tmp_path: Path) -> None:
    _write_agent(tmp_path)
    registry = await _build_registry(tmp_path, "alibaba_search")
    plan = registry.assemble("finder", "research")
    assert plan.skill_id == "research"
    assert "全局约束" in plan.system_prompt
    assert "完整工作流" in plan.system_prompt
    assert "参考文档" in plan.system_prompt
    assert "门禁" in plan.system_prompt
    assert plan.required_mcp_servers == ["alibaba_search"]
    assert plan.core_tool_names == ["search", "search_news"]
    # 声明脚本 + 带校验器的门禁注册为脚本工具（graph-runtime-spec §6）
    assert {s.name for s in plan.scripts} == {"run_research", "gate_sources_collected"}
    gate = next(s for s in plan.scripts if s.name == "gate_sources_collected")
    assert gate.schema_path == "schemas/gate_input.json"  # 门禁入参约束挂载
    assert plan.env_whitelist == ["FINDER_API_KEY"]
    assert plan.model_preference == "qwen-max"


async def test_assemble_default_skill(tmp_path: Path) -> None:
    _write_agent(tmp_path)
    registry = await _build_registry(tmp_path, "alibaba_search")
    plan = registry.assemble("finder", None)
    assert plan.skill_id == "research"


async def test_assemble_unknown_skill_raises(tmp_path: Path) -> None:
    _write_agent(tmp_path)
    registry = await _build_registry(tmp_path, "alibaba_search")
    with pytest.raises(RegistryValidationError):
        registry.assemble("finder", "nope")


async def test_assemble_unknown_agent_raises(tmp_path: Path) -> None:
    _write_agent(tmp_path)
    registry = await _build_registry(tmp_path, "alibaba_search")
    with pytest.raises(RegistryValidationError):
        registry.assemble("nope", None)


async def test_assemble_capability_resolves_to_candidates(tmp_path: Path) -> None:
    _write_agent(
        tmp_path,
        skill_md=_skill_md(
            mcp_dependencies=[],
            capability_dependencies=[
                {"capability": "web_search", "core_tools": [], "required": True}
            ],
        ),
    )
    registry = await _build_registry(
        tmp_path,
        "alibaba_search",
        "yuanbao_search",
        capabilities={"web_search": ["alibaba_search", "yuanbao_search"]},
    )
    plan = registry.assemble("finder", "research")
    assert plan.required_mcp_servers == []
    assert len(plan.capabilities) == 1
    cap = plan.capabilities[0]
    assert cap.capability == "web_search"
    assert cap.candidate_servers == ["alibaba_search", "yuanbao_search"]
    assert cap.required is True


async def test_capability_not_registered_marks_skill_invalid(tmp_path: Path) -> None:
    _write_agent(
        tmp_path,
        skill_md=_skill_md(
            mcp_dependencies=[],
            capability_dependencies=[{"capability": "ghost_cap", "required": True}],
        ),
    )
    snapshot = await _load(tmp_path, "alibaba_search")
    package = snapshot.packages["finder"]
    assert package.skill_failures
    assert "能力未注册" in package.skill_failures[0].invalid_reason


# ---- 热重载 ----
async def test_hot_reload_disabled_returns_immediately(tmp_path: Path) -> None:
    _write_agent(tmp_path)
    registry = await _build_registry(tmp_path, "alibaba_search")
    reloader = HotReloader(registry, Settings(_env_file=None, hot_reload_enabled=False))
    await reloader.run()


async def test_refresh_replaces_snapshot(tmp_path: Path) -> None:
    _write_agent(tmp_path)
    registry = await _build_registry(tmp_path, "alibaba_search")
    assert "finder" in registry.snapshot.packages
    (tmp_path / "finder" / "AGENT.md").write_text(_agent_md(body="新的约束\n"), encoding="utf-8")
    snapshot = await registry.refresh()
    package = snapshot.packages["finder"]
    assert "新的约束" in package.manifest.body
