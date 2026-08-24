import asyncio
import json

import httpx

default_query = (
    "我是成都派兹互连电子技术有限公司的销售，我正在拓展客户，帮我找找潜在客户。\n\n"
    "【产品】我们主营：高频高速互连器件 / 【板对板、线对板连接器】，\n"
    "       主要用于服务器、数据中心的高速信号传输场景（请替换成您实际产品名+用途）。\n"
    "【目标行业】通信、服务器、数据中心相关制造业\n"
    "【目标区域】全国\n"
    "【客户规模】不限\n"
    "【排除条件】无\n"
    "【报告数量】5 家\n"
    "【销售节奏】均衡\n"
    "信息已给齐，直接开始搜索、评分并生成客户发现报告，不需要再向我确认需求。"
)

DONE_MARKER = "[DONE]"


async def _type_text(text: str, char_delay: float) -> None:
    """模拟前端打字渲染：逐字输出到控制台。"""
    for ch in text:
        print(ch, end="", flush=True)
        await asyncio.sleep(char_delay)


async def test_chat_completions(
    api_client: httpx.AsyncClient,
    base_url: str,
    query: str = default_query,
    conversation_id: str = "",
    response_mode: str = "streaming",
    char_delay: float = 0.02,
) -> list[str]:
    url = f"{base_url}/api/v1/chat-messages"

    payload = {
        "query": query,
        "conversation_id": conversation_id,
        "response_mode": response_mode,
    }

    headers = {
        "accept": "application/json",
        "content-type": "application/json",
    }

    answers: list[str] = []
    message_id: str | None = None
    stream_conversation_id: str | None = None

    async with api_client.stream("POST", url, headers=headers, json=payload) as response:
        assert response.status_code == 200

        async for line in response.aiter_lines():
            if not line.startswith("data: "):
                continue

            data = line[6:]
            if data == DONE_MARKER:
                break

            try:
                frame = json.loads(data)
            except json.JSONDecodeError:
                continue

            if frame.get("event") == "ping":
                # SSE 心跳帧，无正文，跳过
                continue

            message_id = frame.get("message_id") or message_id
            stream_conversation_id = frame.get("conversation_id") or stream_conversation_id

            answer = frame.get("answer")
            if isinstance(answer, str) and answer:
                answers.append(answer)
                await _type_text(answer, char_delay)

    print()
    print("=" * 42)
    print("流式回答汇总")
    print("=" * 42)
    print(f"message_id      : {message_id}")
    print(f"conversation_id : {stream_conversation_id}")
    print(f"回答片段数      : {len(answers)}")
    print(f"完整回答        : {''.join(answers)}")
    return answers
