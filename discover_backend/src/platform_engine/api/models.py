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
