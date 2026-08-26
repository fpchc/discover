"""API 请求 / 响应模型：接入层对外契约（跨边界一律 pydantic）。

对话接口契约：`POST /chat-messages`，请求体含
`query` / `response_mode` / `conversation_id`；`streaming` 走 SSE
（`event` 判别帧），`blocking` 返回 JSON。`files` 字段接受但暂不处理。
"""

from typing import Literal

from pydantic import BaseModel, Field


class ChatMessageRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    response_mode: Literal["streaming", "blocking"] = "streaming"
    conversation_id: str = ""
    # 用户显式助手选择：空 = 沿用/不绑定；"generic" = 通用对话；其余 = 专家 id
    agent_id: str = Field(default="", max_length=100)


class ChatMessageResponse(BaseModel):
    """blocking 响应（chat-messages 形状）。"""

    message_id: str
    mode: Literal["chat"] = "chat"
    answer: str
    metadata: dict[str, object] = Field(default_factory=dict)
    conversation_id: str
    created_at: int


class MessageEvent(BaseModel):
    """流式正文增量帧。"""

    event: Literal["message"] = "message"
    message_id: str
    conversation_id: str
    answer: str
    created_at: int


class MessageEndEvent(BaseModel):
    """流式收尾帧。"""

    event: Literal["message_end"] = "message_end"
    message_id: str
    conversation_id: str
    metadata: dict[str, object] = Field(default_factory=dict)
    created_at: int


class PingEvent(BaseModel):
    """心跳帧。"""

    event: Literal["ping"] = "ping"


class ErrorStreamEvent(BaseModel):
    """错误帧。"""

    event: Literal["error"] = "error"
    status: int
    code: str
    message: str


class ThinkingStartFrame(BaseModel):
    """思考开始帧（DeepSeek 式思考分区：前端据此打开折叠思考框）。

    Frame 后缀为对外 SSE 帧，区别于 protocol/events.py 的内部事件
    （ThinkingStartedEvent 等，routes_chat 同时 import 两者避免同名冲突）。
    """

    event: Literal["thinking_started"] = "thinking_started"
    message_id: str
    conversation_id: str
    created_at: int


class ThinkingDeltaFrame(BaseModel):
    """思考增量帧：思考过程文字逐段到达，前端追加到思考分区。"""

    event: Literal["thinking_delta"] = "thinking_delta"
    message_id: str
    conversation_id: str
    content: str
    created_at: int


class ThinkingEndFrame(BaseModel):
    """思考结束帧：携带思考耗时，前端折叠思考分区。"""

    event: Literal["thinking_ended"] = "thinking_ended"
    message_id: str
    conversation_id: str
    duration_ms: int
    created_at: int
