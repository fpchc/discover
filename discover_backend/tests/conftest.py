from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from app.bootstrap.application import create_app
from app.config.settings import Settings
from app.domain.auth.security import JwtService
from sqlalchemy import text

# 测试固定 JWT 密钥（≥32 字节，避免 pyjwt 弱密钥警告；与 _build_settings 对齐）
_TEST_JWT_SECRET = "test-secret-0123456789abcdef0123456789abcdef"
# 测试令牌默认账号（虚构 uuid；JWT 解签不查库，隔离过滤按此字符串）
_TEST_ACCOUNT_ID = "00000000-0000-0000-0000-0000000000aa"


def make_auth_token(account_id: str = _TEST_ACCOUNT_ID, *, secret: str = _TEST_JWT_SECRET) -> str:
    """构造有效 JWT（认证依赖仅解签，不查库，任意 account_id 可过）。"""
    return JwtService(Settings(_env_file=None, jwt_secret_key=secret)).encode(account_id)


@pytest.fixture()
def auth_headers() -> dict[str, str]:
    """受保护路由的 Authorization 头（默认测试账号）。"""
    return {"Authorization": f"Bearer {make_auth_token()}"}


@pytest.fixture()
def auth_headers_other() -> dict[str, str]:
    """第二个账号的 Authorization 头（跨账号隔离用例）。"""
    return {"Authorization": f"Bearer {make_auth_token('00000000-0000-0000-0000-0000000000bb')}"}


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
        # 关闭日志扩展：其非阻塞配置会替换根 logger handler，破坏 pytest 日志捕获
        logging_enabled=False,
        # 认证恒启用（无 auth_enabled 开关）；测试注入固定密钥（≥32 字节）
        jwt_secret_key="test-secret-0123456789abcdef0123456789abcdef",
    )


class _FakeSessionStore:
    """内存会话存储（离线 HTTP 测试用）：访问会话恒有效，登出/刷新走内存 dict。

    exists_access 恒 True：测试令牌经 make_auth_token / JwtService 直接签发、不写
    会话，需保持「有效 JWT 即可访问」语义（等价原 NullSessionStore 行为）；
    create/consume/revoke 真实落内存，供登出 / 刷新端点用例。Redis 会话层为
    硬依赖，此处注入避免依赖真实 Redis（CLAUDE.md §12）。
    """

    def __init__(self) -> None:
        self._access: dict[str, str] = {}
        self._refresh: dict[str, str] = {}

    async def create_access(self, token: str, account_id: str, *, ttl_seconds: int) -> None:
        del ttl_seconds
        self._access[token] = account_id

    async def exists_access(self, token: str) -> bool:
        del token
        return True

    async def create_refresh(self, token: str, account_id: str, *, ttl_seconds: int) -> None:
        del ttl_seconds
        self._refresh[token] = account_id

    async def get_refresh(self, token: str) -> str | None:
        return self._refresh.get(token)

    async def consume_refresh(self, token: str) -> str | None:
        return self._refresh.pop(token, None)

    async def revoke_access(self, token: str) -> None:
        self._access.pop(token, None)

    async def revoke_refresh(self, token: str) -> None:
        self._refresh.pop(token, None)


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
    否则 services.conversation_service 等只在 startup() 里创建，路由会断言失败。
    """
    app = create_app(_build_settings(tmp_path))
    async with app.router.lifespan_context(app):
        # Redis 会话层为硬依赖；离线测试注入内存假存储（startup 已建 AuthService）
        app.state.services.auth._sessions = _FakeSessionStore()  # type: ignore[attr-defined]  # 测试注入假会话存储
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://127.0.0.1:8000/"
        ) as client:
            yield app, client


@pytest.fixture()
async def require_db(
    api_ctx: tuple[object, httpx.AsyncClient],
) -> AsyncIterator[None]:
    """对话记录续聊/删除用例守卫：需要本地 PostgreSQL，不可达则 skip。

    对话记录唯一事实来源为 DB；离线 http 集合不再提供内存会话注册表，
    凡依赖「上一轮落库可读」的用例必须连库（docker compose 起 PG）。
    """
    app, _client = api_ctx
    db = app.state.services.db
    try:
        async with db.session_factory() as session:
            await session.execute(text("SELECT 1"))
    except Exception:
        pytest.skip("本地 PostgreSQL 不可达（对话记录续聊/删除用例需 DB）")
    yield
