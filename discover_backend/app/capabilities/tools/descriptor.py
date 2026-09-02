"""工具描述符与命名空间（tool-broker-spec §3-§4）。

限定名命名空间规则只在本文实现一处：服务标识连字符转下划线。
描述符在装配期生成，不在运行时构造。
"""

from enum import StrEnum

from pydantic import BaseModel, Field

from app.capabilities.llm.models import ChatToolSpec, ToolFunction
from app.config.settings import SideEffectType
from app.domain.skill.manifest import ScriptDeclaration


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
    """统一工具目录条目。装配期生成，运行时只读。"""

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
    script_decl: ScriptDeclaration | None = None
    host_script_path: str | None = None


def to_chat_tool_spec(descriptor: ToolDescriptor) -> ChatToolSpec:
    """描述符 → OpenAI 工具规格（供 LLM 请求）。"""
    return ChatToolSpec(
        function=ToolFunction(
            name=descriptor.qualified_name,
            description=descriptor.description,
            parameters=descriptor.parameters,
        )
    )
