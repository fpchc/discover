from collections.abc import AsyncIterator
from pathlib import Path

import anyio
import httpx
import pytest

from platform_engine.api.app import create_app
from platform_engine.config.settings import Settings
from platform_engine.protocol.events import DoneEvent
from platform_engine.runtime.state import GraphState

# 目录 → marker 映射：四层测试结构，按目录自动打标（pytest 9 的 conftest pytestmark
# 不再传播到同目录模块，故用 collection 钩子统一处理）
_LAYER_MARKERS: dict[str, str] = {
    "unit": "unit",
    "integration": "integration",
    "http": "http",
    "e2e": "e2e",
}
_TESTS_ROOT = Path(__file__).resolve().parent

AGENT_MD = """\
---
agent_id: finder
display_name: 客户发现
version: 1.0.0
description: 发现潜在客户
scope:
  applies: 用户想找潜在客户时
  does_not_apply: 用户想写周报时
default_skill: research
skills:
  - research
---
全局约束：语气专业。
"""

SKILL_MD = """\
---
skill_id: research
version: 1.0.0
description: 客户调研
scope:
  applies: 需要调研时
  does_not_apply: 纯闲聊
---
完整工作流。
"""

LLM_YAML = """\
providers:
  - id: qwen-max
    display_name: "Qwen"
    base_url: "https://llm.example.com/v1"
    api_key_env: "LLM_API_KEY"
    model: "qwen-max"
    supports_thinking: true
    thinking_field: "reasoning_content"
    context_window: 131072
"""

MCP_YAML = """\
servers:
  - id: alibaba_search
    transport: streamable_http
    base_url: "https://mcp.example.com"
"""


def _build_settings(tmp_path: Path) -> Settings:
    agents = tmp_path / "agents"
    agent_dir = agents / "finder"
    (agent_dir / "research").mkdir(parents=True)
    (agent_dir / "AGENT.md").write_text(AGENT_MD, encoding="utf-8")
    (agent_dir / "research" / "SKILL.md").write_text(SKILL_MD, encoding="utf-8")
    (tmp_path / "llm-providers.yaml").write_text(LLM_YAML, encoding="utf-8")
    (tmp_path / "mcp-servers.yaml").write_text(MCP_YAML, encoding="utf-8")
    return Settings(
        _env_file=None,
        agents_root_dir=agents,
        agent_workspace_root_dir=tmp_path / "workspaces",
        storage_root_dir=tmp_path / "storage",
        llm_providers_path=tmp_path / "llm-providers.yaml",
        mcp_registry_path=tmp_path / "mcp-servers.yaml",
        tool_log_root_dir=tmp_path / "logs",
        hot_reload_enabled=False,
    )


class _FakeRuntime:
    """测试用假运行时：模拟 LLM 流式增量到达，不触达真实 LLM。

    分块推送正文（含间隔），由服务端 emitter 按 typewriter 节流分帧——
    消费者按帧到达追加即可看到打字机效果。
    """

    async def run_turn(self, *, session_id: str, user_input: str, emitter: object) -> GraphState:
        del session_id, user_input
        for chunk in ("你好，", "我是平台智能体，", "正在流式输出。"):
            emitter.text_delta(chunk)
            await anyio.sleep(0.05)
        await emitter.emit(DoneEvent(turns=1, duration_ms=0, usage={}))
        return GraphState()

    async def close(self) -> None:
        """AppServices.shutdown 会逐一 close 会话运行时。"""


def pytest_configure(config: pytest.Config) -> None:
    # 每个测试独立事件循环：session 级循环 + async generator fixture 会在
    # teardown 触发 pytest-asyncio 的 Runner.run()「running event loop」报错
    config.option.asyncio_loop_scope = "function"


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        rel = Path(str(item.path)).resolve().relative_to(_TESTS_ROOT)
        marker_name = _LAYER_MARKERS.get(rel.parts[0]) if rel.parts else None
        if marker_name is not None:
            item.add_marker(getattr(pytest.mark, marker_name))


@pytest.fixture()
async def api_ctx(tmp_path: Path) -> AsyncIterator[tuple[object, httpx.AsyncClient]]:
    """进程内测试上下文：(app, httpx 客户端)。

    httpx.ASGITransport 直连 ASGI 应用，无需真服务；手动跑 lifespan，
    否则 services.sessions 等只在 startup() 里创建，路由会断言失败。
    """
    app = create_app(_build_settings(tmp_path))
    app.state.services.get_runtime = lambda _sid: _FakeRuntime()
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://127.0.0.1:8000/"
        ) as client:
            yield app, client
