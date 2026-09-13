"""工具端口词汇：描述符、限定名规则与调用/结果模型（tool-broker-spec §3-§4、§11）。

单一动机：定义「运行时与工具之间」的稳定契约。这些模型是纯值对象与命名规则，
不触达 MCP、子进程或数据库——具体工具代理实现位于
`app/infrastructure/tools/`（依赖方向：infrastructure → domain）。
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from app.config.settings import SideEffectType
from app.environment.tools.plan import ScriptSpec
from app.llm.models import ChatToolSpec, ToolFunction
from app.shared.errors.base import ErrorCategory


class ToolSource(StrEnum):
    """工具来源类型。"""

    MCP = "mcp"
    SCRIPT = "script"
    META = "meta"


def _sanitize_segment(segment: str) -> str:
    """命名空间片段规范化：连字符转下划线（保证工具名符合命名约束）。"""
    return segment.replace("-", "_")


def mcp_qualified_name(server_id: str, tool_name: str) -> str:
    """MCP 工具限定名：服务标识（连字符转下划线）+ 点号 + 工具名。"""
    return f"{_sanitize_segment(server_id)}.{tool_name}"


def script_qualified_name(agent_id: str, skill_id: str, tool_name: str) -> str:
    """技能脚本工具限定名：智能体 + 技能 + script. + 工具名。"""
    return f"{agent_id}.{skill_id}.script.{tool_name}"


def split_qualified_name(name: str) -> tuple[str, str]:
    """拆限定名为 (命名空间, 短名)。无命名空间返回 ("", name)。"""
    if "." in name:
        namespace, short = name.rsplit(".", 1)
        return namespace, short
    return "", name


class ToolDescriptor(BaseModel):
    """统一工具目录条目。装配期生成，运行时只读。

    扩展（react-runtime-v2-architecture §15.1）：
    idempotent / retryable / max_attempts / fingerprint_ignore_fields / phase_tags，
    供 Tool Runtime 管线做重复判定、有界重试与幂等策略；旧字段保留默认值兼容。
    """

    qualified_name: str
    short_name: str
    namespace: str
    description: str
    parameters: dict[str, object] = Field(default_factory=dict)
    source: ToolSource
    tier: int
    side_effect: SideEffectType = SideEffectType.READ_ONLY
    timeout_seconds: float | None = None
    source_ref: str = ""
    script_decl: ScriptSpec | None = None
    host_script_path: str | None = None
    # ---- §15.1 扩展 ----
    idempotent: bool = False
    retryable: bool = False
    max_attempts: int = 1
    fingerprint_ignore_fields: list[str] = Field(default_factory=list)
    phase_tags: list[str] = Field(default_factory=list)


class ToolCallRequest(BaseModel):
    """一次工具调用请求。"""

    call_id: str
    tool_name: str
    arguments: dict[str, object] = Field(default_factory=dict)


class ToolResult(BaseModel):
    """工具调用结果（tool-broker-spec §11）。失败时建议字段必须非空。"""

    call_id: str
    tool_name: str
    ok: bool
    content: str = ""
    error_category: ErrorCategory | None = None
    message: str = ""
    suggestion: str | None = None
    duration_ms: int = 0
    truncated: bool = False
    produced_files: list[str] = Field(default_factory=list)


def to_chat_tool_spec(descriptor: ToolDescriptor) -> ChatToolSpec:
    """描述符 → OpenAI 工具规格（供 LLM 请求）。"""
    return ChatToolSpec(
        function=ToolFunction(
            name=descriptor.qualified_name,
            description=descriptor.description,
            parameters=descriptor.parameters,
        )
    )
