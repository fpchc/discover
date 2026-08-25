"""LLM 请求侧模型：与运行时解耦的 OpenAI 兼容请求结构。"""

from typing import Literal

from pydantic import BaseModel, Field


class ToolFunction(BaseModel):
    """工具函数定义（OpenAI tools 格式的 function 部分）。"""

    name: str
    description: str = ""
    parameters: dict[str, object] = Field(default_factory=dict)


class ChatToolSpec(BaseModel):
    """工具清单条目（OpenAI tools 格式）。"""

    type: Literal["function"] = "function"
    function: ToolFunction


class ChatToolCallFunction(BaseModel):
    """助手消息中工具调用的 function 部分。"""

    name: str
    arguments: str


class ChatToolCall(BaseModel):
    """助手消息中一次工具调用。"""

    id: str
    type: Literal["function"] = "function"
    function: ChatToolCallFunction


class ChatMessage(BaseModel):
    """对话消息。角色为 system / user / assistant / tool。"""

    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    tool_calls: list[ChatToolCall] | None = None
    tool_call_id: str | None = None


class ChatRequest(BaseModel):
    """一次流式对话请求。模型标识与思考字段由提供方注册表决定。"""

    messages: list[ChatMessage]
    tools: list[ChatToolSpec] = Field(default_factory=list)
    thinking: bool = False
    temperature: float | None = None
