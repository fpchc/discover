"""工具代理的目录契约与纯辅助函数。

单一动机：把 ToolBroker（目录 / 激活 / 分发）拆开后，这里是环境侧工具通道的
端口形状（MCPManagerPort / ScriptExecutorPort）、激活结果模型与一批不依赖实例
状态的纯函数，被 broker.py 与 broker_dispatch.py 共同依赖。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, Field

from app.environment.mcp.client import MCPClient
from app.environment.tools.models import ToolDescriptor, ToolSource
from app.environment.tools.script_executor import ScriptExecution
from app.shared.errors.base import ErrorCategory, RegistryValidationError

_DEFAULT_SCRIPT_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {"input": {"type": "string"}},
    "required": ["input"],
}
_META_QUERY_LIMIT = 20
_LOG_ARGS_SUMMARY_CHARS = 300
# 触发「会话级数据源降级」的错误分类：计费/鉴权类不可恢复，重试无意义。
_MCP_DEGRADE_CATEGORIES: frozenset[ErrorCategory] = frozenset(
    {ErrorCategory.BILLING, ErrorCategory.AUTH}
)


class MCPManagerPort(Protocol):
    """工具代理依赖的 MCP 管理器抽象（DIP）。"""

    async def acquire(self, server_id: str) -> MCPClient: ...
    def release(self, server_id: str) -> None: ...
    def concurrency_limit(self, server_id: str) -> int: ...


class ScriptExecutorPort(Protocol):
    """工具代理依赖的脚本执行器抽象（DIP）。"""

    async def run(
        self,
        *,
        host_script: Path,
        skill_dir: Path,
        workspace: Path,
        args: dict[str, object],
        env_whitelist: list[str],
        timeout_seconds: float,
    ) -> ScriptExecution: ...


class ToolActivation(BaseModel):
    """技能激活结果：启动服务、降级项、失败项。"""

    ok: bool
    core_count: int = 0
    catalog_size: int = 0
    started_services: list[str] = Field(default_factory=list)
    degraded_services: list[str] = Field(default_factory=list)
    degrade_notes: list[str] = Field(default_factory=list)
    failed_required: list[str] = Field(default_factory=list)
    reason: str | None = None


class ToolHit(BaseModel):
    """检索命中项：只含名称、来源与简要说明，不含参数约束（§9）。"""

    qualified_name: str
    description: str
    source: ToolSource


def _read_json(path: Path) -> dict[str, object]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RegistryValidationError(f"入参约束文件非法：{path}") from exc
    return data if isinstance(data, dict) else {}


def _similarity(left: str, right: str) -> int:
    """命名空间分片重叠度，用于相近工具候选。"""
    left_parts = set(left.split("."))
    right_parts = set(right.split("."))
    return len(left_parts & right_parts)


def _extract_upsert(stdout: str) -> tuple[dict[str, object] | None, str]:
    """从脚本 stdout 提取 `_upsert` 回写载荷，并从模型可见内容中移除。"""
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return None, stdout
    if not isinstance(data, dict):
        return None, stdout
    upsert = data.pop("_upsert", None)
    if not isinstance(upsert, dict):
        return None, stdout
    return upsert, json.dumps(data, ensure_ascii=False, indent=2)


def _extract_section(text: str, section: str) -> str:
    """按标题分段，返回命中的段；未命中返回全文。"""
    active = "开头"
    sections: dict[str, list[str]] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            active = stripped.lstrip("#").strip()
        sections.setdefault(active, []).append(line)
    for key, body in sections.items():
        if section in key:
            return "\n".join(body)
    return text


def _coerce_nested_object_args(
    descriptor: ToolDescriptor, arguments: dict[str, object]
) -> dict[str, object]:
    """把「被模型序列化成 JSON 字符串的嵌套对象/数组字段」回转为原生类型。

    通用分派工具（tyc_mcp.call_tool / call_tools_batch）声明 arguments 为 object，但推理
    模型常把内层 arguments 连同外层一起 JSON 序列化成字符串，远端 MCP 据此报
    「arguments must be an object」，导致数据采集全部失败、最终无正文。分派字段名
    arguments / calls 语义固定，按字段名确定性回退（不依赖远端 schema 是否准确声明
    type）；其余字段仅当 schema 声明 object/array 时才解析，绝不猜测。
    """
    props = descriptor.parameters.get("properties")
    props = props if isinstance(props, dict) else {}
    out = dict(arguments)
    for field, value in list(out.items()):
        if not isinstance(value, str):
            continue
        parsed = _try_parse_json(value)
        if field == "arguments" and isinstance(parsed, dict):
            out[field] = parsed
            continue
        if field == "calls" and isinstance(parsed, list):
            out[field] = [_coerce_call_item(item) for item in parsed]
            continue
        schema = props.get(field)
        declared = schema.get("type") if isinstance(schema, dict) else None
        if (declared == "object" and isinstance(parsed, dict)) or (
            declared == "array" and isinstance(parsed, list)
        ):
            out[field] = parsed
    return out


def _coerce_call_item(item: object) -> object:
    """批量分派 calls 数组内单个元素的 arguments 字段回转为对象。"""
    if not isinstance(item, dict):
        return item
    raw = item.get("arguments")
    if isinstance(raw, str):
        parsed = _try_parse_json(raw)
        if isinstance(parsed, dict):
            return {**item, "arguments": parsed}
    return item


def _try_parse_json(value: str) -> object:
    """把 JSON 字符串解析为原生对象；非法返回原字符串。"""
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _resolve_script_host(skill_dir: Path, rel: str) -> Path | None:
    candidate = skill_dir / Path(rel)
    if candidate.is_file():
        return candidate
    return None


def _read_doc(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
