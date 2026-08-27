"""Step 9 HTTP 接入层测试（chat-messages 接口）。

- blocking / 会话复用 / 参数校验用例：进程内 httpx ASGI，无需真服务。
- 流式打字机用例：真调用 127.0.0.1:8000 接口（本地服务未启动自动 skip），
  正文增量按帧到达追加输出——打字机节奏由服务端 emitter 节流（每帧 2 字/30ms）
  驱动，客户端不二次节流，达到 ChatGPT 式逐字出现效果。
SSE 帧与 blocking 响应均为跨边界 DTO（CLAUDE.md §3）：一律经 pydantic 模型
校验后类型化访问。判别联合在 test 内本地定义，复用项目既有 DTO。
"""

from typing import Annotated

import httpx
import pytest
from app.schemas import (
    ChatMessageResponse,
    ErrorStreamEvent,
    MessageEndEvent,
    MessageEvent,
    PingEvent,
    ThinkingDeltaFrame,
    ThinkingEndFrame,
    ThinkingStartFrame,
)
from pydantic import Field, TypeAdapter

_LOCAL_BASE_URL = "http://127.0.0.1:8000"

# 项目 SSE 帧判别联合（跨边界 DTO，event 字段判别）
type StreamFrame = Annotated[
    MessageEvent
    | MessageEndEvent
    | PingEvent
    | ErrorStreamEvent
    | ThinkingStartFrame
    | ThinkingDeltaFrame
    | ThinkingEndFrame,
    Field(discriminator="event"),
]
STREAM_ADAPTER = TypeAdapter(StreamFrame)


def _parse_sse_line(line: str) -> StreamFrame | None:
    """解析单行 SSE：`data:` 载荷按 event 判别校验为跨边界 DTO；非帧行返回 None。"""
    if not line.startswith("data: "):
        return None
    return STREAM_ADAPTER.validate_json(line[len("data: ") :])


query = (
    "我是成都派兹互连电子技术有限公司的销售，我正在拓展客户，帮我找找潜在客户。\n\n"
    "【产品】我们主营：高频高速互连器件 / 【板对板、线对板连接器】，\n"
    "       主要用于服务器、数据中心的高速信号传输场景（请替换成您实际产品名+用途）。\n"
    "【目标行业】通信、服务器、数据中心相关制造业\n"
    "【目标区域】全国\n【客户规模】不限\n【排除条件】无\n【报告数量】5 家\n【销售节奏】均衡\n"
    "信息已给齐，直接开始搜索、评分并生成客户发现报告，不需要再向我确认需求。"
)


async def _local_server_up() -> bool:
    """探测本地 8000 服务（绕过系统代理，防 HTTP_PROXY 拦截 localhost 致 502）。"""
    transport = httpx.AsyncHTTPTransport(trust_env=False)
    try:
        async with httpx.AsyncClient(transport=transport, timeout=1.0) as probe:
            await probe.get(f"{_LOCAL_BASE_URL}/")
        return True
    except httpx.HTTPError:
        return False


async def test_chat_messages_streaming_auto_creates_conversation() -> None:
    """真接口流式打字机：调用本地服务，正文按帧到达追加输出到控制台。"""
    if not await _local_server_up():
        pytest.skip("本地服务未启动（127.0.0.1:8000）")
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(300.0, connect=5.0),
        trust_env=False,  # 绕过系统代理直连本地
    ) as client:
        answers: list[str] = []
        events: set[str] = set()
        saw_done = False
        message_end: MessageEndEvent | None = None
        async with client.stream(
            "POST",
            f"{_LOCAL_BASE_URL}/api/v1/chat-messages",
            json={"query": query, "response_mode": "streaming"},
        ) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            assert response.headers["x-accel-buffering"] == "no"
            conversation_id = response.headers["x-conversation-id"]
            assert conversation_id
            async for line in response.aiter_lines():
                if line == "data: [DONE]":
                    saw_done = True
                    continue
                frame = _parse_sse_line(line)
                if frame is None:
                    continue
                events.add(frame.event)
                if isinstance(frame, MessageEvent):
                    answers.append(frame.answer)
                    print(frame.answer, end="", flush=True)  # 按帧到达追加，节奏由服务端节流
                elif isinstance(frame, MessageEndEvent):
                    message_end = frame
        print()  # 收尾换行，结束打字行
        assert not saw_done
        assert message_end is not None
        assert "message" in events
        assert "message_end" in events
        assert "".join(answers)
        assert message_end.conversation_id == conversation_id


async def test_chat_messages_blocking_returns_json(
    api_ctx: tuple[object, httpx.AsyncClient],
) -> None:
    _app, client = api_ctx
    response = await client.post(
        "/api/v1/chat-messages",
        json={"query": "你好", "response_mode": "blocking"},
    )
    assert response.status_code == 200
    payload = ChatMessageResponse.model_validate(response.json())
    assert payload.mode == "chat"
    assert payload.answer == "你好，我是平台智能体，正在流式输出。"
    assert payload.conversation_id
    assert payload.metadata["usage"] == {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "cached_read_tokens": 0,
        "cached_write_tokens": 0,
    }
    assert response.headers["x-conversation-id"] == payload.conversation_id


async def test_chat_messages_reuses_conversation(
    api_ctx: tuple[object, httpx.AsyncClient],
) -> None:
    _app, client = api_ctx
    first = await client.post(
        "/api/v1/chat-messages",
        json={"query": "第一轮", "response_mode": "blocking"},
    )
    conversation_id = ChatMessageResponse.model_validate(first.json()).conversation_id
    second = await client.post(
        "/api/v1/chat-messages",
        json={
            "query": "第二轮",
            "response_mode": "blocking",
            "conversation_id": conversation_id,
        },
    )
    assert second.status_code == 200
    assert second.headers["x-conversation-id"] == conversation_id
    assert ChatMessageResponse.model_validate(second.json()).conversation_id == conversation_id
    # 未知会话 → 404
    missing = await client.post(
        "/api/v1/chat-messages",
        json={"query": "hi", "response_mode": "blocking", "conversation_id": "nope"},
    )
    assert missing.status_code == 404


async def test_chat_messages_empty_query_rejected(
    api_ctx: tuple[object, httpx.AsyncClient],
) -> None:
    _app, client = api_ctx
    response = await client.post(
        "/api/v1/chat-messages",
        json={"query": "", "response_mode": "blocking"},
    )
    assert response.status_code == 422


# ---- 助手目录与显式选择 ----
async def test_assistants_catalog_lists_experts_only(
    api_ctx: tuple[object, httpx.AsyncClient],
) -> None:
    """GET /assistants：只列专家；通用对话为默认态，不列入目录。"""
    _app, client = api_ctx
    response = await client.get("/api/v1/assistants")
    assert response.status_code == 200
    data = response.json()
    by_id = {entry["id"]: entry for entry in data}
    assert set(by_id) == {"finder"}
    assert by_id["finder"]["type"] == "expert"
    assert by_id["finder"]["name"] == "客户发现"
    assert by_id["finder"]["capabilities"] == ["research"]


async def test_chat_binds_expert_by_agent_id(
    api_ctx: tuple[object, httpx.AsyncClient],
) -> None:
    """首轮显式选择专家 → 响应 metadata.assistant 携带 type+id。"""
    _app, client = api_ctx
    response = await client.post(
        "/api/v1/chat-messages",
        json={"query": "帮我找客户", "response_mode": "blocking", "agent_id": "finder"},
    )
    assert response.status_code == 200
    payload = ChatMessageResponse.model_validate(response.json())
    assert payload.metadata["assistant"] == {"type": "expert", "id": "finder"}


async def test_chat_unknown_agent_returns_404(
    api_ctx: tuple[object, httpx.AsyncClient],
) -> None:
    """未知 agent_id → 404（目录校验失败）。"""
    _app, client = api_ctx
    response = await client.post(
        "/api/v1/chat-messages",
        json={"query": "hi", "response_mode": "blocking", "agent_id": "nope"},
    )
    assert response.status_code == 404


async def test_chat_generic_agent_id_selects_generic(
    api_ctx: tuple[object, httpx.AsyncClient],
) -> None:
    """agent_id=generic（保留字）→ 通用对话目标。"""
    _app, client = api_ctx
    response = await client.post(
        "/api/v1/chat-messages",
        json={"query": "你好", "response_mode": "blocking", "agent_id": "generic"},
    )
    assert response.status_code == 200
    payload = ChatMessageResponse.model_validate(response.json())
    assert payload.metadata["assistant"] == {"type": "generic", "id": None}


async def test_chat_rebind_switches_assistant(
    api_ctx: tuple[object, httpx.AsyncClient],
) -> None:
    """续聊携带新 agent_id → 切换绑定（专家 → 通用）。"""
    _app, client = api_ctx
    first = await client.post(
        "/api/v1/chat-messages",
        json={"query": "hi", "response_mode": "blocking", "agent_id": "finder"},
    )
    conversation_id = ChatMessageResponse.model_validate(first.json()).conversation_id
    second = await client.post(
        "/api/v1/chat-messages",
        json={
            "query": "hi",
            "response_mode": "blocking",
            "conversation_id": conversation_id,
            "agent_id": "generic",
        },
    )
    payload = ChatMessageResponse.model_validate(second.json())
    assert payload.metadata["assistant"] == {"type": "generic", "id": None}


# ---- 会话删除（DELETE /conversations/{id}） ----
class _FakeHistoryService:
    """路由测试桩：替身历史服务，隔离真实 DB（CLAUDE.md §12 Mock 红线）。"""

    def __init__(self, exists: bool) -> None:
        self._exists = exists

    async def soft_delete_conversation(self, conversation_id: str) -> bool:
        return self._exists


async def test_delete_conversation_returns_204(
    api_ctx: tuple[object, httpx.AsyncClient],
) -> None:
    """DB 有历史 → 删除并返回 204 空体。"""
    app, client = api_ctx
    app.state.services.history = _FakeHistoryService(exists=True)
    response = await client.delete("/api/v1/conversations/cafebabe")
    assert response.status_code == 204
    assert response.content == b""


async def test_delete_conversation_unknown_returns_404(
    api_ctx: tuple[object, httpx.AsyncClient],
) -> None:
    """DB 历史与内存会话皆无 → 404。"""
    app, client = api_ctx
    app.state.services.history = _FakeHistoryService(exists=False)
    response = await client.delete("/api/v1/conversations/nope")
    assert response.status_code == 404
