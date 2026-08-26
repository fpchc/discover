"""流式分片语义分类与工具调用累积。

llm-provider-spec §4：把原始分片归类为语义单元（思考/正文/工具调用/阶段
切换/结束原因/用量），不向上透传提供方原始格式。

llm-provider-spec §6：工具调用参数跨分片累积；拼接完成判据是结束原因指示
工具调用，而非「参数看起来像完整 JSON」。
"""

import json
from typing import Annotated, Literal

from pydantic import BaseModel, Field, TypeAdapter


class ToolCall(BaseModel):
    """一次完整的工具调用（累积完成后）。"""

    index: int
    id: str | None = None
    name: str | None = None
    arguments: str = ""


class _ToolCallAccumulator(BaseModel):
    """工具调用跨分片累积器（内部状态，不跨边界）。"""

    id: str | None = None
    name: str | None = None
    arguments: list[str] = Field(default_factory=list)


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


def _int_value(value: object) -> int:
    return value if isinstance(value, int) else 0


def _nested_int(usage: dict[str, object], path: list[str]) -> int:
    """沿路径取嵌套整数值；任一环节非 dict 返回 0。"""
    current: object = usage
    for key in path:
        if not isinstance(current, dict):
            return 0
        current = current.get(key)
    return _int_value(current)


class StreamParser:
    """流式分片语义分类器。每行 feed 产出该行的语义单元列表。"""

    def __init__(self, *, thinking_field: str | None) -> None:
        self._thinking_field = thinking_field
        self._tool_calls: dict[int, _ToolCallAccumulator] = {}
        self._phase: Literal["thinking", "text", "tool_call", "idle"] = "idle"

    def feed(self, data: str) -> list[SemanticChunk]:
        """解析一行 SSE data 载荷，产出语义单元列表。非 JSON 行返回空。"""
        try:
            payload: object = json.loads(data)
        except json.JSONDecodeError:
            return []
        if not isinstance(payload, dict):
            return []
        return self._classify(payload)

    def _classify(self, payload: dict[str, object]) -> list[SemanticChunk]:
        chunks: list[SemanticChunk] = []
        usage = payload.get("usage")
        if isinstance(usage, dict):
            chunks.append(self._usage_chunk(usage))
        choices = payload.get("choices")
        if not isinstance(choices, list):
            return chunks
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            delta = choice.get("delta")
            if isinstance(delta, dict):
                chunks.extend(self._classify_delta(delta))
            finish = choice.get("finish_reason")
            if isinstance(finish, str) and finish:
                chunks.append(FinishChunk(reason=finish))
                if finish == "tool_calls":
                    chunks.append(ToolCallsChunk(tool_calls=self._assembled_tool_calls()))
        return chunks

    def _classify_delta(self, delta: dict[str, object]) -> list[SemanticChunk]:
        chunks: list[SemanticChunk] = []
        thinking_text = self._extract_thinking(delta)
        if thinking_text:
            chunks.extend(self._phase_chunks("thinking"))
            chunks.append(ThinkingChunk(text=thinking_text))
        content = delta.get("content")
        if isinstance(content, str) and content:
            chunks.extend(self._phase_chunks("text"))
            chunks.append(TextChunk(text=content))
        tool_calls = delta.get("tool_calls")
        if isinstance(tool_calls, list):
            for raw in tool_calls:
                if isinstance(raw, dict):
                    chunks.extend(self._phase_chunks("tool_call"))
                    chunks.append(self._tool_call_chunk(raw))
        return chunks

    def _extract_thinking(self, delta: dict[str, object]) -> str:
        if self._thinking_field is None:
            return ""
        value = delta.get(self._thinking_field)
        return value if isinstance(value, str) else ""

    def _phase_chunks(self, to: Literal["thinking", "text", "tool_call"]) -> list[SemanticChunk]:
        if self._phase == to:
            return []
        self._phase = to
        return [PhaseSwitchChunk(to=to)]

    def _tool_call_chunk(self, raw: dict[str, object]) -> ToolCallChunk:
        raw_index = raw.get("index")
        index = raw_index if isinstance(raw_index, int) else 0
        accumulator = self._tool_calls.setdefault(index, _ToolCallAccumulator())
        raw_id = raw.get("id")
        if isinstance(raw_id, str) and raw_id:
            accumulator.id = raw_id
        arguments: str | None = None
        function = raw.get("function")
        if isinstance(function, dict):
            name = function.get("name")
            if isinstance(name, str) and name:
                accumulator.name = name
            args_part = function.get("arguments")
            if isinstance(args_part, str) and args_part:
                accumulator.arguments.append(args_part)
                arguments = args_part
        return ToolCallChunk(
            index=index,
            id=accumulator.id,
            name=accumulator.name,
            arguments=arguments,
        )

    def _usage_chunk(self, usage: dict[str, object]) -> UsageChunk:
        return UsageChunk(
            input_tokens=_int_value(usage.get("prompt_tokens")),
            output_tokens=_int_value(usage.get("completion_tokens")),
            total_tokens=_int_value(usage.get("total_tokens")),
            cached_read_tokens=self._cached_read_tokens(usage),
            cached_write_tokens=_int_value(usage.get("cache_creation_input_tokens")),
        )

    @staticmethod
    def _cached_read_tokens(usage: dict[str, object]) -> int:
        """兼容三种提供方惯例：OpenAI / DeepSeek / Anthropic 风格。"""
        openai = _nested_int(usage, ["prompt_tokens_details", "cached_tokens"])
        deepseek = _int_value(usage.get("prompt_cache_hit_tokens"))
        anthropic = _int_value(usage.get("cache_read_input_tokens"))
        return openai or deepseek or anthropic

    def _assembled_tool_calls(self) -> list[ToolCall]:
        calls: list[ToolCall] = []
        for index in sorted(self._tool_calls):
            accumulator = self._tool_calls[index]
            calls.append(
                ToolCall(
                    index=index,
                    id=accumulator.id,
                    name=accumulator.name,
                    arguments="".join(accumulator.arguments),
                )
            )
        return calls
