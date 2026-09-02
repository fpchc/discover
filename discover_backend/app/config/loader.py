"""模型提供方与 MCP 服务注册表的 yaml 加载。

注册表文件是数据（非代码）。文件读写与解析走 anyio 线程池，避免阻塞事件循环。
"""

import os
import re
from pathlib import Path
from typing import Literal, Self

import anyio
import yaml
from pydantic import BaseModel, Field, ValidationError, model_validator

from app.shared.errors.base import ConfigError

_ENV_PATTERN = re.compile(r"\$\{([^}:]+)(?::-([^}]*))?\}")


class LLMProvider(BaseModel):
    """模型提供方注册项。密钥只存环境变量名，值在调用时从环境读取。"""

    id: str
    display_name: str
    base_url: str
    api_key_env: str
    model: str
    supports_thinking: bool = False
    thinking_field: str | None = None
    supports_tool_calling: bool = True
    context_window: int
    timeout_seconds: float = 60.0
    retries: int = 2


class LLMRegistry(BaseModel):
    """模型提供方注册表：智能体偏好别名映射 + 提供方列表。"""

    aliases: dict[str, str] = Field(default_factory=dict)
    providers: list[LLMProvider] = Field(default_factory=list)


class MCPServerAuth(BaseModel):
    """MCP 服务认证配置。令牌只存环境变量名，值在调用时从环境读取。"""

    type: Literal["bearer_token"] = "bearer_token"
    token_env: str | None = None


class MCPServer(BaseModel):
    """MCP 服务注册项。"""

    id: str
    transport: Literal["streamable_http"]
    base_url: str
    auth: MCPServerAuth = Field(default_factory=MCPServerAuth)
    per_session: bool = False
    handshake_timeout_seconds: float | None = None
    call_timeout_seconds: float = 30.0
    concurrency_limit: int = 3
    enabled: bool = True


class MCSCapability(BaseModel):
    """平台能力（技能与具体服务之间的抽象层，agent-package-spec §4）。

    技能只声明「需要某个能力」，具体由哪些提供方供给由本注册表决定；
    加 / 删 / 换提供方只改此处，不触碰技能清单。

    strategy: "failover" 主备切换——按 servers 顺序优先，第一个可用者生效，
    失败自动切换下一个；全失败时按依赖的 required 决定拒绝激活或降级。
    "all" 全部候选激活——候选服务器各自作为独立工具进目录，调用哪个由模型
    （re-act）推理决定，不做切换也不做降级。用于多搜索提供方并存场景。

    fallback: 能力级降级（系统机制，非提示词）。本能力全部候选服务器不可用时，
    装配层解析 fallback 指向的能力的候选服务器继续尝试；命中则视为「已降级为
    fallback 能力」继续激活，降级说明由系统生成。只允许一级降级（fallback 能力
    自身不得再声明 fallback），防环。strategy="all" 时忽略 fallback。
    """

    servers: list[str] = Field(min_length=1)
    strategy: Literal["failover", "all"] = "failover"
    fallback: str | None = None


class MCPRegistry(BaseModel):
    """MCP 服务注册表。"""

    servers: list[MCPServer] = Field(default_factory=list)
    capabilities: dict[str, MCSCapability] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_capability_servers(self) -> Self:
        known = {server.id for server in self.servers}
        for name, capability in self.capabilities.items():
            missing = [sid for sid in capability.servers if sid not in known]
            if missing:
                raise ValueError(f"能力 {name} 引用了未注册的服务器：{', '.join(missing)}")
            if capability.fallback is not None:
                if capability.fallback == name:
                    raise ValueError(f"能力 {name} 的降级目标不能指向自身")
                if capability.fallback not in self.capabilities:
                    raise ValueError(f"能力 {name} 的降级目标未注册：{capability.fallback}")
                if self.capabilities[capability.fallback].fallback is not None:
                    raise ValueError(
                        f"能力 {name} 降级目标 {capability.fallback} 不能再声明降级（仅一级）"
                    )
        return self

    def server_enabled(self, server_id: str) -> bool:
        """查询服务显式开关（enabled: false 的条目装配时被剔除，不尝试连接）。

        未知服务返回 True——交由调用方正常报错，不因查询失败而静默过滤。
        """
        for server in self.servers:
            if server.id == server_id:
                return server.enabled
        return True


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _parse_yaml(raw: str) -> dict[str, object]:
    parsed: object = yaml.safe_load(raw)
    if not isinstance(parsed, dict):
        raise ConfigError("yaml 顶层必须是映射")
    return {str(key): value for key, value in parsed.items()}


async def _load_yaml_registry(path: Path, *, kind: str) -> dict[str, object]:
    try:
        raw = await anyio.to_thread.run_sync(_read_text, path)
    except OSError as exc:
        raise ConfigError(f"无法读取{kind}注册表：{path}") from exc
    return await anyio.to_thread.run_sync(_parse_yaml, raw)


async def load_llm_providers(path: Path) -> LLMRegistry:
    """异步加载模型提供方注册表。文件缺失或格式非法抛 ConfigError。"""
    data = await _load_yaml_registry(path, kind="模型提供方")
    try:
        return LLMRegistry.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"模型提供方注册表校验失败：{path}：{exc}") from exc


async def load_mcp_servers(path: Path) -> MCPRegistry:
    """异步加载 MCP 服务注册表。文件缺失或格式非法抛 ConfigError。

    读取后先做 `${VAR}` / `${VAR:-default}` 环境变量替换（部署差异，如 docker 内
    tencent_mcp / eastmoney_mcp 容器地址），再做 YAML 解析。未设置的变量取默认值，无默认则为空串。
    """
    try:
        raw = await anyio.to_thread.run_sync(_read_text, path)
    except OSError as exc:
        raise ConfigError(f"无法读取MCP服务注册表：{path}") from exc
    raw = _substitute_env(raw)
    data = await anyio.to_thread.run_sync(_parse_yaml, raw)
    try:
        return MCPRegistry.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"MCP 服务注册表校验失败：{path}：{exc}") from exc


def _substitute_env(text: str) -> str:
    """替换 `${VAR}` 与 `${VAR:-default}` 为环境变量值（真实 os.environ）。"""

    def _replace(match: re.Match[str]) -> str:
        name = match.group(1)
        default = match.group(2)
        value = os.environ.get(name)
        if value is None or value == "":
            return default if default is not None else ""
        return value

    return _ENV_PATTERN.sub(_replace, text)
