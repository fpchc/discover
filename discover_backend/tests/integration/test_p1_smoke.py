"""Step 11 P1 端到端冒烟测试（不依赖 LLM/MCP 密钥；Docker 可选）。

覆盖：
- discover 智能体包加载与装配（真实 agents/ 目录 + 真实 MCP 注册表）
- 脚本 stdin/stdout 契约（score_calculator / dedup_manager / render_report --check-only
  与 gate_render_valid）
- 报告渲染（jinja2 可用时全量渲染到工作区 output/）
- 真实注册表 + 假 LLM/MCP 的两级路由端到端（无需密钥）

真实 LLM/MCP 调用无密钥属预期失败，不在本文件范围；容器执行需 Docker，
此处仅验证宿主脚本契约，容器运行由平台运行时承担。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from app.capabilities.llm.providers import ProviderRegistry
from app.capabilities.llm.stream_parser import (
    FinishChunk,
    PhaseSwitchChunk,
    TextChunk,
)
from app.capabilities.mcp.client import MCPCallResult, MCPToolInfo
from app.capabilities.tools.script_executor import ScriptExecution
from app.config.loader import (
    LLMProvider,
    load_llm_providers,
    load_mcp_servers,
)
from app.config.settings import Settings
from app.domain.assistant.models import AssistantTarget, TargetType
from app.domain.file.service import FileService
from app.domain.skill.loader import _find_absolute_path_literals
from app.domain.skill.registry import AgentRegistry
from app.domain.workspace.service import WorkspaceManager
from app.infrastructure.database.engine import Database
from app.infrastructure.storage.local import LocalStorage
from app.runtime.engine import Runtime
from app.runtime.events.emitter import QueueEmitter
from app.runtime.events.events import (
    AgentEvent,
    AgentSelectedEvent,
    DoneEvent,
    SkillSelectedEvent,
    ToolsReadyEvent,
)

ROOT = Path(__file__).resolve().parent.parent.parent
AGENTS_DIR = ROOT / "agents"
MCP_REGISTRY_PATH = ROOT / "config" / "mcp-servers.yaml"
LLM_PROVIDERS_PATH = ROOT / "config" / "llm-providers.yaml"
SKILL_DIR = AGENTS_DIR / "discover" / "client-finder"
SCRIPTS_DIR = SKILL_DIR / "scripts"
_SCORE_DIMS = (
    "purchase_scale",
    "tech_match",
    "demand_intensity",
    "purchase_timing",
    "competitive_pos",
    "reach_feasibility",
    "decision_complex",
    "credit_safety",
)


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        agents_root_dir=AGENTS_DIR,
        agent_workspace_root_dir=tmp_path / "workspaces",
        storage_root_dir=tmp_path / "storage",
        mcp_registry_path=MCP_REGISTRY_PATH,
        tool_log_root_dir=tmp_path / "logs",
        hot_reload_enabled=False,
    )


_DATABASE = Database(Settings(_env_file=None))

# 图会话标识与归属账号（对话记录由 ConversationService 管理，Runtime 只做透传）
_SESSION_ID = "00000000-0000-0000-0000-0000000000cc"
_ACCOUNT = "00000000-0000-0000-0000-0000000000cc"


async def _discover_registry(tmp_path: Path) -> AgentRegistry:
    settings = _settings(tmp_path)
    mcp = await load_mcp_servers(settings.mcp_registry_path)
    registry = AgentRegistry(settings, mcp)
    await registry.refresh()
    return registry


def _jinja2_missing() -> bool:
    try:
        import jinja2  # noqa: F401
    except ImportError:
        return True
    return False


def _run_script(
    script: Path,
    *,
    args: list[str] | None = None,
    stdin_data: str | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    base_env = os.environ.copy()
    base_env.update({"PYTHONIOENCODING": "utf-8"})
    if env:
        base_env.update(env)
    return subprocess.run(
        [sys.executable, str(script), *(args or [])],
        input=stdin_data,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=base_env,
        timeout=60,
    )


# ---- 包加载 ----
def test_discover_package_loads(tmp_path: Path) -> None:
    import asyncio

    async def load() -> None:
        registry = await _discover_registry(tmp_path)
        snapshot = registry.snapshot
        assert snapshot.failures == [], [f.model_dump() for f in snapshot.failures]
        pkg = registry.get_agent("discover")
        assert pkg is not None
        assert pkg.skill_failures == [], [f.model_dump() for f in pkg.skill_failures]
        assert pkg.manifest.kind == "agent"
        assert pkg.manifest.type == "expert"
        assert set(pkg.skills) == {"client-finder"}
        skill = pkg.skills["client-finder"]
        # 门禁校验器注册为脚本工具（graph-runtime-spec §6）
        assert any(g.validator is not None for g in skill.gates)
        plan = registry.assemble("discover", None)
        assert plan.required_mcp_servers == ["alibaba_search"]
        assert {s.name for s in plan.scripts} >= {
            "score_calculator",
            "render_report",
            "gate_render_pass",
        }

    asyncio.run(load())


def test_discover_scripts_have_no_absolute_path_literals() -> None:
    hits = _find_absolute_path_literals(SCRIPTS_DIR)
    assert hits == []


# ---- 脚本契约 ----
def test_score_calculator_contract() -> None:
    payload = {
        "companies": [
            {
                "company_name": "锐捷网络股份有限公司",
                "uscc": "X",
                "scores": {
                    "purchase_scale": 8.0,
                    "tech_match": 9.0,
                    "demand_intensity": 7.0,
                    "purchase_timing": 7.5,
                    "competitive_pos": 6.0,
                    "reach_feasibility": 8.0,
                    "decision_complex": 4.0,
                    "credit_safety": 9.0,
                },
                "red_flags": {},
            }
        ],
        "top_n": 5,
    }
    result = _run_script(
        SCRIPTS_DIR / "score_calculator.py", stdin_data=json.dumps(payload, ensure_ascii=False)
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    # 参考样例：综合分 7.63（与迁移源 score_calculator 输出一致）
    assert data["rankings"][0]["composite_score"] == 7.63
    assert data["rankings"][0]["status"] == "推荐"


def test_score_calculator_red_flag_excludes() -> None:
    payload = {
        "companies": [
            {
                "company_name": "失信企业",
                "uscc": "X",
                "scores": dict.fromkeys(_SCORE_DIMS, 8.0),
                "red_flags": {"dishonesty": True},
            }
        ],
        "top_n": 5,
    }
    result = _run_script(
        SCRIPTS_DIR / "score_calculator.py", stdin_data=json.dumps(payload, ensure_ascii=False)
    )
    data = json.loads(result.stdout)
    assert data["rankings"] == []
    assert data["excluded"][0]["excluded_reason"] == "失信被执行人"


def test_dedup_manager_contract() -> None:
    empty_history = {"version": "1.0", "product_clues": []}
    add = {
        "history": empty_history,
        "mode": "add",
        "clue_data": {
            "product_keywords": ["高速背板连接器"],
            "target_industry": "数据中心交换机",
            "recommendations": [
                {"company_name": "锐捷网络股份有限公司", "uscc": "X", "status": "已推荐"}
            ],
        },
    }
    added = _run_script(
        SCRIPTS_DIR / "dedup_manager.py", stdin_data=json.dumps(add, ensure_ascii=False)
    )
    assert added.returncode == 0
    add_data = json.loads(added.stdout)
    assert add_data["success"] is True
    clue = add_data["_upsert"]
    assert clue["clue_id"]
    exclude = {
        "history": {"version": "1.0", "product_clues": [clue]},
        "mode": "exclude",
        "product_keywords": ["高速背板连接器"],
        "target_industry": "数据中心交换机",
    }
    excluded = _run_script(
        SCRIPTS_DIR / "dedup_manager.py",
        stdin_data=json.dumps(exclude, ensure_ascii=False),
    )
    data = json.loads(excluded.stdout)
    assert data["matched"] is True
    assert data["all_excluded"][0]["company_name"] == "锐捷网络股份有限公司"


def test_render_check_only_and_gate_validator(tmp_path: Path) -> None:
    report = _sample_report()
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    env = {"WORKSPACE_DIR": str(tmp_path), "SKILL_ROOT_DIR": str(SKILL_DIR)}
    checked = _run_script(
        SCRIPTS_DIR / "render_report.py", args=[str(report_path), "--check-only"], env=env
    )
    assert checked.returncode == 0, checked.stdout + checked.stderr
    assert "结构校验通过" in checked.stdout
    gate = _run_script(
        SCRIPTS_DIR / "gate_render_valid.py",
        stdin_data=json.dumps({"report_json": str(report_path)}, ensure_ascii=False),
        env=env,
    )
    assert gate.returncode == 0, gate.stdout
    assert json.loads(gate.stdout)["passed"] is True


@pytest.mark.skipif(
    _jinja2_missing(), reason="jinja2 未安装，跳过全量渲染（--check-only 已覆盖结构校验）"
)
def test_render_full_produces_html(tmp_path: Path) -> None:
    report = _sample_report()
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    output_dir = tmp_path / "output"
    env = {"WORKSPACE_DIR": str(tmp_path), "SKILL_ROOT_DIR": str(SKILL_DIR)}
    result = _run_script(SCRIPTS_DIR / "render_report.py", args=[str(report_path)], env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    html_files = list(output_dir.glob("*.html"))
    assert len(html_files) == 1
    content = html_files[0].read_text(encoding="utf-8")
    assert "{{" not in content  # 无 Jinja 残留
    assert "高速背板连接器" in content


# ---- 端到端路由（假 LLM/MCP，无密钥） ----
class _FakeLLM:
    """脚本化 LLM：推理返回固定文本（助手由用户显式绑定，无 LLM 路由）。"""

    async def stream_chat(self, *, provider: LLMProvider, api_key: str, request: object) -> object:
        del provider, api_key, request
        yield PhaseSwitchChunk(to="text")
        yield TextChunk(text="好的，我帮你找电子信息产业链的潜在客户。")
        yield FinishChunk(reason="stop")


class _FakeMCPClient:
    call_timeout_seconds = 30.0

    async def list_tools(self) -> list[MCPToolInfo]:
        return [
            MCPToolInfo(
                name="web_search", description="公开网页搜索", input_schema={"type": "object"}
            )
        ]

    async def call_tool(self, name: str, arguments: dict[str, object]) -> MCPCallResult:
        del name, arguments
        return MCPCallResult(content="搜索结果")


class _FakeMCPManager:
    def __init__(self) -> None:
        self.acquired: list[str] = []

    async def acquire(self, server_id: str) -> _FakeMCPClient:
        self.acquired.append(server_id)
        return _FakeMCPClient()

    def release(self, server_id: str) -> None:
        pass

    def concurrency_limit(self, server_id: str) -> int:
        del server_id
        return 2


class _FakeScriptExecutor:
    async def run(self, **kwargs: object) -> ScriptExecution:
        del kwargs
        return ScriptExecution(exit_code=0, stdout="ok")


async def test_route_discover_end_to_end(tmp_path: Path) -> None:
    import anyio

    settings = _settings(tmp_path)
    registry = await _discover_registry(tmp_path)
    # 真实提供方注册表：含 opus/sonnet → qwen-max 别名（discover AGENT 模型偏好）
    providers = ProviderRegistry(await load_llm_providers(LLM_PROVIDERS_PATH))
    runtime = Runtime(
        settings=settings,
        workspaces=WorkspaceManager(settings),
        files=FileService(settings, _DATABASE, LocalStorage(tmp_path / "storage")),
        registry=registry,
        llm=_FakeLLM(),  # type: ignore[arg-type]
        providers=providers,
        resolve_api_key=lambda _provider: "dummy",
        mcp_manager=_FakeMCPManager(),  # type: ignore[arg-type]
        script_executor=_FakeScriptExecutor(),  # type: ignore[arg-type]
        db=_DATABASE,
    )
    emitter = QueueEmitter(Settings(_env_file=None))
    final = await runtime.run_turn(
        session_id=_SESSION_ID,
        user_input="我卖高速背板连接器，帮我找客户",
        emitter=emitter,
        account_id=_ACCOUNT,
        assistant_target=AssistantTarget(type=TargetType.EXPERT, id="discover"),
    )
    await emitter.finish()
    events: list[AgentEvent] = []
    while True:
        try:
            with anyio.fail_after(0.05):
                events.append(await emitter.get())
        except TimeoutError:
            break
    assert final.active_target == AssistantTarget(type=TargetType.EXPERT, id="discover")
    assert final.active_skill == "client-finder"
    assert any(isinstance(e, AgentSelectedEvent) for e in events)
    assert any(isinstance(e, SkillSelectedEvent) for e in events)
    assert any(isinstance(e, ToolsReadyEvent) for e in events)
    assert any(isinstance(e, DoneEvent) for e in events)
    assert any(m.role == "assistant" and "潜在客户" in (m.content or "") for m in final.messages)
    await runtime.close()


# ---- 样例报告（模板 schema 为准，见 report-structure.md §四·五） ----
def _sample_report() -> dict[str, object]:
    def client(index: int, name: str) -> dict[str, object]:
        return {
            "fullname": name,
            "display_name": name,
            "score": 7.6 - index,
            "rank": index + 1,
            "tags": "连接器",
            "kpi_row": "注册资本 1 亿 | 参保 500 人",
            "oneliner": "数据中心交换机厂商",
            "basic_table": "公开登记信息",
            "equity_section": "实控人：XX（持股 40%）。股权结构相对集中。来源：公开搜索。",
            "match_highlights": [
                {"dim": "技术匹配", "fact": "产品直接使用高速连接器", "value": "高", "icon": "✅"}
            ],
            "match_risks": [
                {"dim": "采购时机", "issue": "采购周期较长", "impact": "周期 6-12 个月"}
            ],
            "veto_check": "未触发红线",
            "contacts_intro": "关键决策人如下",
            "decision_insight": "决策链较短",
            "decision_chain": "采购总监 → 技术负责人",
            "signal_insight": "近期扩产",
            **{
                f"match_subscore_{j}": {
                    "label": [
                        "采购规模",
                        "技术匹配",
                        "需求强度",
                        "采购时机",
                        "竞争位置",
                        "触达可行",
                        "决策复杂度",
                        "信用安全",
                    ][j - 1],
                    "score": 7.0,
                    "weight": "20%",
                    "sub_scores": {"子维度": 3},
                    "raw_data": "搜索可得",
                    "source": "公开搜索",
                }
                for j in range(1, 9)
            },
            "procurement": {
                "scale_label": "中型",
                "estimate_range": "50-150 万/年",
                "confidence": "中",
                "confidence_color": "confidence-mid",
                "method": "规模推算",
                "base_calc": {
                    "base_value": 500,
                    "base_source": "参保人数",
                    "coefficients": [{"name": "人均采购额", "value": 1000, "reason": "行业均值"}],
                    "formula": "参保x人均采购额",
                },
                "drivers": ["扩产", "招标"],
                "supplier_trend": "有现有供应商",
                "calc_note": "估算",
                "evidence_items": [
                    {"body": "扩产新闻", "source": "公开搜索"},
                    {"body": "招聘 30 人", "source": "公开搜索"},
                    {"body": "招标公告", "source": "公开搜索"},
                ],
            },
            "contact_cards": [
                {
                    "name": "王五",
                    "title": "采购总监",
                    "type": "决策人",
                    "source": "公开搜索未能识别到决策人·降级",
                    "source_confidence": "低",
                    "fields": [{"label": "决策角色", "value": "采购"}],
                    "bio": "公开信息有限",
                    "gov_role": "",
                    "buyer": "",
                    "confidence": "",
                    "influencer": "",
                    "range": "",
                    "scale": "",
                    "tech": "",
                }
            ],
            "signals": [
                {
                    "category": "招聘",
                    "level": "green",
                    "level_label": "积极",
                    "detail": "扩招 30 人",
                    "date": "2026-08-01",
                    "source": "公开搜索",
                    "metrics": {"岗位数": 30},
                }
            ],
            "engagement": {
                "positioning": "以高速互连技术方案切入",
                "value_props": [{"prop": "性能", "mapping": "56G PAM4"}],
                "entry_points": [
                    {"hook": "技术趋势", "context": "AI 算力推动高速互连", "trend": "上升"}
                ],
                "objection_handlers": [{"objection": "价格", "response": "总拥有成本更低"}],
                "timeline_steps": [
                    {
                        "phase": "首访",
                        "action": "技术交流",
                        "week": "1-2",
                        "goal": "建立联系",
                        "deliverable": "需求清单",
                    }
                ],
                "timing_assessment": {"badge": "中期", "note": "决策周期中等"},
            },
            "competition": {
                "competitors": [
                    {
                        "name": "安费诺",
                        "market_share": "头部",
                        "core_strength": "生态",
                        "core_weakness": "交期",
                        "customer_profile": "大厂",
                        "our_advantage": "交期短",
                        "position": "领先",
                        "weakness": "响应慢",
                    }
                ],
                "current_supplier_inference": "推测有现有供应商（推断）",
                "substitution_path": {
                    "type": "双源导入",
                    "success_rate": "中",
                    "timeline": "6-12 个月",
                    "summary": "分三步导入双源",
                    "total_timeline": "6-12 个月",
                    "key_risk": "现有供应商关系稳固",
                    "steps": [
                        {
                            "phase": "p1",
                            "action": "a",
                            "duration": "1m",
                            "barrier": "b",
                            "owner": "o",
                            "detail": "d",
                            "label": "l",
                            "level": "低",
                        }
                    ],
                },
                "switching_cost": {
                    "financial": {
                        "value": "中",
                        "label": "财务成本",
                        "sub_items": [{"name": "测试费", "cost": "10 万", "note": "一次性"}],
                    },
                    "time": {
                        "value": "中",
                        "label": "时间成本",
                        "sub_items": [{"name": "评估周期", "cost": "2 个月", "note": "验证"}],
                    },
                    "risk": {
                        "value": "低",
                        "label": "风险成本",
                        "sub_items": [{"name": "稳定性", "cost": "低", "note": "已有同型案例"}],
                    },
                },
                "entry_barrier": {
                    "technical": "中",
                    "certification": "低",
                    "relationship": "高",
                    "price": "中",
                },
                "incumbent_strength": "中",
                "our_differentiation": [
                    {"dim": "性能", "them": "56G", "us": "112G", "advantage": "领先"}
                ],
            },
            "risks": [
                {
                    "category": "经营",
                    "level": "risk-mid",
                    "title": "采购周期",
                    "detail": "决策周期 6-12 个月",
                    "mitigation": "提前布局",
                }
            ],
        }

    return {
        "cover": {
            "title": "高速背板连接器<br>潜在客户评估报告",
            "subtitle": "数据中心交换机",
            "product": "高速背板连接器",
            "scope": "中国大陆 · 通信设备、数据中心交换机",
            "date": "2026-08-20",
            "data_date": "2026-08-20",
            "summary": "数据来源受限版本：公开搜索。评估 1 家企业，推荐 1 家。",
            "company_name": "测试公司",
        },
        "l0": {
            "funnel": "漏斗",
            "signal_heatmap": "热力图",
            "top_table": "排名表",
            "top_n": 1,
            "industry": {
                "market_size": {
                    "amount": "2000亿",
                    "unit": "元",
                    "yoy_growth": "15%",
                    "year": "2026",
                    "source": "公开搜索",
                    "sub_segments": [{"name": "数据中心", "share": "60%", "trend": "↑"}],
                },
                "position": {
                    "my_tier": "L2",
                    "my_subcategory": "连接器",
                    "upstream_layers": [
                        {
                            "tier": "L1",
                            "category": "ICT设备",
                            "products": "交换机",
                            "company_examples": ["示例A"],
                        }
                    ],
                    "downstream_direct": [
                        {
                            "tier": "L1",
                            "category": "ICT设备",
                            "products": "服务器",
                            "company_examples": ["示例B"],
                        }
                    ],
                    "downstream_indirect": [],
                },
                "customer_map": [
                    {
                        "sub_industry": "数据中心交换机",
                        "description": "直接用户",
                        "potential": "高",
                        "reason": "高速互连需求",
                    }
                ],
                "competitive_landscape": [{"competitor": "安费诺", "share": "30%", "note": "头部"}],
                "key_trends": [{"trend": "高速率", "driver": "AI 算力", "timeline": "2026-2028"}],
            },
        },
        "clients": [client(0, "锐捷网络股份有限公司")],
        "appendix": {
            "data_log": "数据日志",
            "scoring_method": "公式+权重（B.1 权重 / B.2 打分 / B.3 红线）",
            "glossary": "术语",
            "disclaimer": "免责声明",
            "version": "1.4",
        },
    }
