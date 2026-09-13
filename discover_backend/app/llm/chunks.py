"""LLM 语义分片模型（llm-provider-spec §4）。

单一动机：定义流式输出的「语义单元」词汇——思考/正文/工具调用/阶段切换/
结束原因/用量。提供方私有字段的统一（防腐层）在
`app/infrastructure/llm/stream_parser.py` 完成，此处只保留平台标准形态，
供运行时、上下文投影与用量聚合共同依赖。
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, TypeAdapter


class ToolCall(BaseModel):
    """一次完整的工具调用（累积完成后）。"""

    index: int
    id: str | None = None
    name: str | None = None
    arguments: str = ""


class SemanticChunk(BaseModel):
    """语义单元基类。"""

    kind: str


class ThinkingChunk(SemanticChunk):
    """思考增量。"""

    kind: Literal["thinking"] = "thinking"
    text: str


class TextChunk(SemanticChunk):
    """正文增量。"""

    kind: Literal["text"] = "text"
    text: str


class ToolCallChunk(SemanticChunk):
    """工具调用增量（单分片）。"""

    kind: Literal["tool_call"] = "tool_call"
    index: int
    id: str | None = None
    name: str | None = None
    arguments: str | None = None


class PhaseSwitchChunk(SemanticChunk):
    """阶段切换：思考结束转正文、或转工具调用。"""

    kind: Literal["phase_switch"] = "phase_switch"
    to: Literal["thinking", "text", "tool_call"]


class FinishChunk(SemanticChunk):
    """结束原因。"""

    kind: Literal["finish"] = "finish"
    reason: str


class ToolCallsChunk(SemanticChunk):
    """完整工具调用列表（结束原因指示工具调用时产出）。"""

    kind: Literal["tool_calls"] = "tool_calls"
    tool_calls: list[ToolCall]


class UsageChunk(SemanticChunk):
    """用量统计（防腐层标准形态：提供方私有字段统一为平台字段）。

    cached_read_tokens 为缓存命中（读缓存）token，cached_write_tokens 为
    缓存写入（建缓存）token；input_tokens 取 prompt_tokens 原值。
    """

    kind: Literal["usage"] = "usage"
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cached_read_tokens: int = 0
    cached_write_tokens: int = 0


SemanticChunkUnion = Annotated[
    FinishChunk
    | PhaseSwitchChunk
    | TextChunk
    | ThinkingChunk
    | ToolCallChunk
    | ToolCallsChunk
    | UsageChunk,
    Field(discriminator="kind"),
]

semantic_adapter: TypeAdapter[SemanticChunkUnion] = TypeAdapter(SemanticChunkUnion)
