"""历史记录服务测试——依赖本地 PostgreSQL（conversations/messages 落库）。

用例 ID 用 uuid4 hex（32 字符）保证每次运行新增独立会话/回合，测试幂等。
"""

import uuid

import pytest_asyncio
from app.config.settings import Settings
from app.db.engine import Database
from app.history.models import MessageStatus, TurnRecord, TurnUsage
from app.history.service import ConversationService

_DATABASE = Database(Settings(_env_file=None))


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _dispose_database() -> None:
    yield
    await _DATABASE.dispose()


def _service() -> ConversationService:
    return ConversationService(_DATABASE)


async def test_record_turn_creates_conversation_and_message() -> None:
    service = _service()
    cid = uuid.uuid4().hex
    mid = uuid.uuid4().hex
    ok = await service.record_turn(
        cid,
        TurnRecord(
            message_id=mid,
            query="找潜在客户",
            answer="已找到 5 家",
            thinking="先搜索再评分",
            status=MessageStatus.NORMAL,
            agent_id="finder",
            provider="qwen3.7-max",
            model="qwen3.7-max",
            latency_ms=1234,
            usage=TurnUsage(
                prompt_tokens=100,
                completion_tokens=20,
                total_tokens=120,
                cached_read_tokens=80,
                cached_write_tokens=10,
            ),
            conversation_name="找潜在客户",
        ),
    )
    assert ok is True
    convos = await service.list_conversations(limit=50, offset=0)
    assert any(c.conversation_id == cid for c in convos)
    msgs = await service.get_messages(cid, limit=50, offset=0)
    assert len(msgs) == 1
    msg = msgs[0]
    assert msg.query == "找潜在客户"
    assert msg.answer == "已找到 5 家"
    assert msg.thinking == "先搜索再评分"
    assert msg.agent_id == "finder"
    assert msg.cached_read_tokens == 80
    assert msg.cached_write_tokens == 10
    usage = await service.get_usage(cid)
    assert usage["message_count"] == 1
    assert usage["prompt_tokens"] == 100
    assert usage["completion_tokens"] == 20
    assert usage["total_tokens"] == 120
    assert usage["cached_read_tokens"] == 80
    assert usage["cached_write_tokens"] == 10


async def test_record_turn_increments_dialogue_and_preserves_name() -> None:
    service = _service()
    cid = uuid.uuid4().hex
    await service.record_turn(
        cid,
        TurnRecord(message_id=uuid.uuid4().hex, query="第一问", conversation_name="第一问标题"),
    )
    await service.record_turn(
        cid,
        TurnRecord(message_id=uuid.uuid4().hex, query="第二问", conversation_name="不应覆盖"),
    )
    convos = await service.list_conversations(limit=50, offset=0)
    convo = next(c for c in convos if c.conversation_id == cid)
    assert convo.dialogue_count == 2
    assert convo.name == "第一问标题"  # 首回合标题保留，续聊不覆盖
    msgs = await service.get_messages(cid, limit=50, offset=0)
    assert [m.query for m in msgs] == ["第一问", "第二问"]


async def test_record_turn_error_status_persisted() -> None:
    service = _service()
    cid = uuid.uuid4().hex
    ok = await service.record_turn(
        cid,
        TurnRecord(
            message_id=uuid.uuid4().hex,
            query="会报错",
            status=MessageStatus.ERROR,
            error="限流",
        ),
    )
    assert ok is True
    msgs = await service.get_messages(cid, limit=50, offset=0)
    assert len(msgs) == 1
    assert msgs[0].status == MessageStatus.ERROR
    assert msgs[0].error == "限流"


async def test_get_usage_empty_conversation() -> None:
    service = _service()
    cid = uuid.uuid4().hex
    usage = await service.get_usage(cid)
    assert usage["message_count"] == 0
    assert usage["prompt_tokens"] == 0
    assert usage["cached_read_tokens"] == 0
