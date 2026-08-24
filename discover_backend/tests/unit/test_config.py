"""Step 2 配置与错误层测试。"""

from pathlib import Path

import pytest

from platform_engine.config.loader import load_llm_providers, load_mcp_servers
from platform_engine.config.settings import Settings
from platform_engine.errors.base import ConfigError

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
"""


def test_settings_defaults() -> None:
    settings = Settings(_env_file=None)
    assert settings.agents_root_dir == Path("agents")
    assert settings.agent_workspace_root_dir == Path("workspaces")
    assert settings.reasoning_max_turns == 40
    assert settings.routing_confidence_threshold == 0.6
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


async def test_load_missing_file_raises_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        await load_llm_providers(tmp_path / "nope.yaml")


async def test_load_invalid_yaml_raises_config_error(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("providers: not-a-list-of-anything", encoding="utf-8")
    with pytest.raises(ConfigError):
        await load_llm_providers(path)
