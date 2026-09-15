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


class ChatStopResponse(BaseModel):
    """stop 接口响应：stopping 取消已请求 / idle 无进行中回合。

    stopping 只承诺「取消已请求」，不代表落库已完成（前端以 SSE 流关闭为准）。
    """

    conversation_id: str
    status: Literal["stopping", "idle"]
    message_id: str | None = None


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
    # 运行标识：断线续传时据此查询 /runs/{run_id} 重放（RunStarted 起即携带）
    run_id: str = ""


class PingEvent(BaseModel):
    """心跳帧。"""

    event: Literal["ping"] = "ping"


class ErrorStreamEvent(BaseModel):
    """错误帧。"""

    event: Literal["error"] = "error"
    status: int
    code: str
    message: str
    run_id: str = ""


class ThinkingStartFrame(BaseModel):
    """思考开始帧（DeepSeek 式思考分区：前端据此打开折叠思考框）。

    Frame 后缀为对外 SSE 帧，区别于 protocol/events.py 的内部事件
    （ThinkingStartedEvent 等，chat.py 同时 import 两者避免同名冲突）。
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


class RunReplayResponse(BaseModel):
    """断线续传 / 运行查询响应：快照摘要 + 持久事件 + 最后序号。"""

    run_id: str
    status: str
    reason: str | None = None
    final_output: str = ""
    last_seq: int = 0
    events: list[dict[str, object]] = Field(default_factory=list)


class RunResumeResponse(BaseModel):
    """断线续传恢复响应：重新获取租约结果 + 快照摘要 + 副作用 action 状态。

    轻量 resume（不做整图恢复）：返回快照/事件 + 未闭环副作用 action，供调用方判断
    是否有「已计划但未落 executed/failed」的动作。
    """

    run_id: str
    status: str
    reason: str | None = None
    final_output: str = ""
    last_seq: int = 0
    lease_reacquired: bool = False
    has_inflight_side_effects: bool = False
    pending_actions: list[dict[str, object]] = Field(default_factory=list)
    events: list[dict[str, object]] = Field(default_factory=list)
