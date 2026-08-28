"""历史记录服务测试——依赖本地 PostgreSQL（conversations/messages 落库）。

用例 ID 用 uuid4 hex（32 字符）保证每次运行新增独立会话/回合，测试幂等。
账号关联：回合归属一个测试账号（无外键，任意 uuid 文本即可）；跨账号隔离
另见 test_auth.py。
"""

import uuid

import pytest_asyncio
from app.config.settings import Settings
from app.conversations.models import ConversationStatus, MessageStatus, TurnRecord, TurnUsage
from app.conversations.service import ConversationService
from app.db.engine import Database
from app.db.models import Conversation

_DATABASE = Database(Settings(_env_file=None))
_ACCOUNT_ID = str(uuid.uuid4())


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
            account_id=_ACCOUNT_ID,
        ),
    )
    assert ok is True
    convos = await service.list_conversations(_ACCOUNT_ID, limit=50, offset=0)
    assert any(c.conversation_id == cid for c in convos)
    msgs = await service.get_messages(_ACCOUNT_ID, cid, limit=50, offset=0)
    assert len(msgs) == 1
    msg = msgs[0]
    assert msg.query == "找潜在客户"
    assert msg.answer == "已找到 5 家"
    assert msg.thinking == "先搜索再评分"
    assert msg.agent_id == "finder"
    assert msg.cached_read_tokens == 80
    assert msg.cached_write_tokens == 10


async def test_record_turn_increments_dialogue_and_preserves_name() -> None:
    service = _service()
    cid = uuid.uuid4().hex
    await service.record_turn(
        cid,
        TurnRecord(
            message_id=uuid.uuid4().hex,
            query="第一问",
            conversation_name="第一问标题",
            account_id=_ACCOUNT_ID,
        ),
    )
    await service.record_turn(
        cid,
        TurnRecord(
            message_id=uuid.uuid4().hex,
            query="第二问",
            conversation_name="不应覆盖",
            account_id=_ACCOUNT_ID,
        ),
    )
    convos = await service.list_conversations(_ACCOUNT_ID, limit=50, offset=0)
    convo = next(c for c in convos if c.conversation_id == cid)
    assert convo.dialogue_count == 2
    assert convo.name == "第一问标题"  # 首回合标题保留，续聊不覆盖
    msgs = await service.get_messages(_ACCOUNT_ID, cid, limit=50, offset=0)
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
            account_id=_ACCOUNT_ID,
        ),
    )
    assert ok is True
    msgs = await service.get_messages(_ACCOUNT_ID, cid, limit=50, offset=0)
    assert len(msgs) == 1
    assert msgs[0].status == MessageStatus.ERROR
    assert msgs[0].error == "限流"


async def test_soft_delete_marks_deleted_and_hides_from_list() -> None:
    service = _service()
    cid = uuid.uuid4().hex
    await service.record_turn(
        cid,
        TurnRecord(
            message_id=uuid.uuid4().hex,
            query="要被删除",
            answer="内容",
            account_id=_ACCOUNT_ID,
        ),
    )
    assert await service.soft_delete_conversation(_ACCOUNT_ID, cid) is True
    # 从列表隐藏
    convos = await service.list_conversations(_ACCOUNT_ID, limit=50, offset=0)
    assert not any(c.conversation_id == cid for c in convos)
    # 行与 messages 保留（token 用量可审计）
    assert len(await service.get_messages(_ACCOUNT_ID, cid, limit=50, offset=0)) == 1


async def test_soft_delete_sets_is_delete_and_preserves_business_status() -> None:
    """软删除置 is_delete=true；业务状态 status 不被覆盖（SRP 拆分后可还原）。"""
    service = _service()
    cid = uuid.uuid4().hex
    await service.record_turn(
        cid,
        TurnRecord(message_id=uuid.uuid4().hex, query="状态保留", account_id=_ACCOUNT_ID),
    )
    assert await service.soft_delete_conversation(_ACCOUNT_ID, cid) is True
    async with _DATABASE.session_factory() as session:
        row = await session.get(Conversation, cid)
        assert row is not None
        assert row.is_delete is True
        assert row.status == ConversationStatus.ACTIVE.value  # 业务状态未随删除覆盖


async def test_soft_delete_already_deleted_returns_false() -> None:
    service = _service()
    cid = uuid.uuid4().hex
    await service.record_turn(
        cid,
        TurnRecord(message_id=uuid.uuid4().hex, query="首次", account_id=_ACCOUNT_ID),
    )
    assert await service.soft_delete_conversation(_ACCOUNT_ID, cid) is True
    assert await service.soft_delete_conversation(_ACCOUNT_ID, cid) is False


async def test_soft_delete_missing_returns_false() -> None:
    service = _service()
    assert await service.soft_delete_conversation(_ACCOUNT_ID, uuid.uuid4().hex) is False


async def test_cross_account_isolation() -> None:
    """跨账号隔离：A 的会话对 B 不可见；B 读/删 A 的会话 → 404/False。"""
    service = _service()
    other = str(uuid.uuid4())
    cid = uuid.uuid4().hex
    await service.record_turn(
        cid,
        TurnRecord(message_id=uuid.uuid4().hex, query="A 的会话", account_id=_ACCOUNT_ID),
    )
    # B 看不到 A 的会话
    assert not any(
        c.conversation_id == cid
        for c in await service.list_conversations(other, limit=50, offset=0)
    )
    # B 读 A 的会话消息 → 404
    from app.errors.base import NotFoundError

    try:
        await service.get_messages(other, cid, limit=50, offset=0)
        raised = False
    except NotFoundError:
        raised = True
    assert raised is True
    # B 删 A 的会话 → False
    assert await service.soft_delete_conversation(other, cid) is False
    # A 的数据仍完整
    assert len(await service.get_messages(_ACCOUNT_ID, cid, limit=50, offset=0)) == 1


async def test_aggregate_user_usage() -> None:
    """按账号聚合 token 用量（messages.created_by 维度）。"""
    service = _service()
    account = str(uuid.uuid4())
    cid1, cid2 = uuid.uuid4().hex, uuid.uuid4().hex
    for cid in (cid1, cid2):
        await service.record_turn(
            cid,
            TurnRecord(
                message_id=uuid.uuid4().hex,
                query="q",
                usage=TurnUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
                account_id=account,
            ),
        )
    usage = await service.aggregate_user_usage(account)
    assert usage.message_count == 2
    assert usage.conversation_count == 2
    assert usage.total_tokens == 30
    assert usage.prompt_tokens == 20
    # 其他账号不受影响
    assert (await service.aggregate_user_usage(str(uuid.uuid4()))).message_count == 0
