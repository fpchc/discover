"""Step 2 配置与错误层测试。"""

from pathlib import Path

import pytest
from app.config.loader import load_llm_providers, load_mcp_servers
from app.config.settings import Settings
from app.shared.errors.base import ConfigError

LLM_YAML = """\
aliases:
  opus: qwen-max
providers:
  - id: qwen-max
    display_name: "Qwen 3.7 Max"
    base_url: "https://dashscope.example.com/v1"
    api_key_env: "LLM_API_KEY"
    model: "qwen-max"
    supports_thinking: true
    thinking_field: "reasoning_content"
    supports_tool_calling: true
    context_window: 131072
    timeout_seconds: 60
    retries: 2
"""

MCP_YAML = """\
servers:
  - id: alibaba_search
    transport: streamable_http
    base_url: "https://mcp.example.com"
    auth:
      type: bearer_token
      token_env: "ALIBABA_SEARCH_TOKEN"
    per_session: false
    call_timeout_seconds: 30
    concurrency_limit: 3
  - id: yuanbao_search
    transport: streamable_http
    base_url: "https://mcp-yuanbao.example.com"
    auth:
      type: bearer_token
      token_env: "YUANBAO_SEARCH_TOKEN"
    per_session: false
    concurrency_limit: 3
capabilities:
  web_search:
    strategy: failover
    servers:
      - alibaba_search
      - yuanbao_search
"""


def test_settings_defaults() -> None:
    settings = Settings(_env_file=None)
    assert settings.agents_root_dir == Path("agents")
    assert settings.agent_workspace_root_dir == Path("workspaces")
    assert settings.reasoning_max_turns == 40
    assert settings.typewriter_frame_interval_ms == 30


def test_settings_env_file_override() -> None:
    settings = Settings(_env_file=None, agents_root_dir=Path("custom-agents"))
    assert settings.agents_root_dir == Path("custom-agents")


async def test_load_llm_providers(tmp_path: Path) -> None:
    path = tmp_path / "llm-providers.yaml"
    path.write_text(LLM_YAML, encoding="utf-8")
    registry = await load_llm_providers(path)
    assert registry.aliases == {"opus": "qwen-max"}
    assert registry.providers[0].id == "qwen-max"
    assert registry.providers[0].supports_thinking is True
    assert registry.providers[0].thinking_field == "reasoning_content"
    assert registry.providers[0].api_key_env == "LLM_API_KEY"


async def test_load_mcp_servers(tmp_path: Path) -> None:
    path = tmp_path / "mcp-servers.yaml"
    path.write_text(MCP_YAML, encoding="utf-8")
    registry = await load_mcp_servers(path)
    assert registry.servers[0].id == "alibaba_search"
    assert registry.servers[0].transport == "streamable_http"
    assert registry.servers[0].auth.token_env == "ALIBABA_SEARCH_TOKEN"
    assert registry.servers[0].per_session is False
    assert registry.servers[1].id == "yuanbao_search"
    assert registry.servers[1].auth.token_env == "YUANBAO_SEARCH_TOKEN"
    capability = registry.capabilities["web_search"]
    assert capability.strategy == "failover"
    assert capability.servers == ["alibaba_search", "yuanbao_search"]


async def test_load_mcp_server_enabled_switch(tmp_path: Path) -> None:
    """enabled 显式开关：解析 + server_enabled 查询；缺省 true；未知服务不静默过滤。"""
    path = tmp_path / "mcp-servers.yaml"
    modified = MCP_YAML.replace(
        "    call_timeout_seconds: 30\n    concurrency_limit: 3",
        "    call_timeout_seconds: 30\n    concurrency_limit: 3\n    enabled: false",
        1,
    )
    path.write_text(modified, encoding="utf-8")
    registry = await load_mcp_servers(path)
    assert registry.servers[0].enabled is False
    assert registry.servers[1].enabled is True  # 缺省 true
    assert registry.server_enabled("alibaba_search") is False
    assert registry.server_enabled("yuanbao_search") is True
    assert registry.server_enabled("ghost_server") is True


async def test_load_mcp_capability_references_missing_server(tmp_path: Path) -> None:
    path = tmp_path / "mcp-servers.yaml"
    path.write_text(
        MCP_YAML.replace(
            "servers:\n      - alibaba_search\n      - yuanbao_search",
            "servers:\n      - alibaba_search\n      - ghost_server",
        ),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="ghost_server"):
        await load_mcp_servers(path)


FALLBACK_MCP_YAML = """\
servers:
  - id: alibaba_search
    transport: streamable_http
    base_url: "https://mcp.example.com"
    auth:
      type: bearer_token
      token_env: "ALIBABA_SEARCH_TOKEN"
    per_session: false
    concurrency_limit: 3
  - id: yuanbao_search
    transport: streamable_http
    base_url: "https://mcp-yuanbao.example.com"
    auth:
      type: bearer_token
      token_env: "YUANBAO_SEARCH_TOKEN"
    per_session: false
    concurrency_limit: 3
  - id: tyc_mcp
    transport: streamable_http
    base_url: "https://tyc.example.com"
    auth:
      type: bearer_token
      token_env: "TYC_MCP_TOKEN"
    per_session: true
    concurrency_limit: 3
capabilities:
  web_search:
    strategy: failover
    servers:
      - alibaba_search
      - yuanbao_search
  enterprise_business:
    strategy: failover
    servers:
      - tyc_mcp
    fallback: web_search
"""


async def test_load_mcp_capability_fallback_parsed(tmp_path: Path) -> None:
    path = tmp_path / "mcp-servers.yaml"
    path.write_text(FALLBACK_MCP_YAML, encoding="utf-8")
    registry = await load_mcp_servers(path)
    cap = registry.capabilities["enterprise_business"]
    assert cap.fallback == "web_search"
    assert cap.servers == ["tyc_mcp"]


async def test_load_mcp_capability_fallback_missing_target(tmp_path: Path) -> None:
    path = tmp_path / "mcp-servers.yaml"
    path.write_text(
        FALLBACK_MCP_YAML.replace("fallback: web_search", "fallback: ghost_cap"),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="ghost_cap"):
        await load_mcp_servers(path)


async def test_load_mcp_capability_fallback_self_rejected(tmp_path: Path) -> None:
    path = tmp_path / "mcp-servers.yaml"
    path.write_text(
        FALLBACK_MCP_YAML.replace("    fallback: web_search", "    fallback: enterprise_business"),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="不能指向自身"):
        await load_mcp_servers(path)


async def test_load_mcp_capability_fallback_two_levels_rejected(tmp_path: Path) -> None:
    path = tmp_path / "mcp-servers.yaml"
    # web_search 也声明 fallback → 二级降级/环 → 拒绝
    modified = FALLBACK_MCP_YAML.replace(
        "  web_search:\n"
        "    strategy: failover\n"
        "    servers:\n"
        "      - alibaba_search\n"
        "      - yuanbao_search\n",
        "  web_search:\n"
        "    strategy: failover\n"
        "    servers:\n"
        "      - alibaba_search\n"
        "      - yuanbao_search\n"
        "    fallback: enterprise_business\n",
    )
    path.write_text(modified, encoding="utf-8")
    with pytest.raises(ConfigError, match="不能再声明降级"):
        await load_mcp_servers(path)


async def test_load_missing_file_raises_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        await load_llm_providers(tmp_path / "nope.yaml")


async def test_load_invalid_yaml_raises_config_error(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("providers: not-a-list-of-anything", encoding="utf-8")
    with pytest.raises(ConfigError):
        await load_llm_providers(path)


async def test_mcp_registry_env_substitution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """注册表 base_url 支持 ${VAR:-default}：未设取默认，docker 设环境变量则覆盖。"""
    monkeypatch.delenv("TENCENT_MCP_BASE_URL", raising=False)
    path = tmp_path / "mcp-servers.yaml"
    path.write_text(
        "servers:\n"
        "  - id: tencent_mcp\n"
        "    transport: streamable_http\n"
        '    base_url: "${TENCENT_MCP_BASE_URL:-http://127.0.0.1:10001/mcp}"\n'
        "capabilities:\n"
        "  web_search:\n"
        "    strategy: all\n"
        "    servers:\n"
        "      - tencent_mcp\n",
        encoding="utf-8",
    )
    registry = await load_mcp_servers(path)
    assert registry.servers[0].base_url == "http://127.0.0.1:10001/mcp"

    monkeypatch.setenv("TENCENT_MCP_BASE_URL", "http://tencent_mcp:10001/mcp")
    registry = await load_mcp_servers(path)
    assert registry.servers[0].base_url == "http://tencent_mcp:10001/mcp"
