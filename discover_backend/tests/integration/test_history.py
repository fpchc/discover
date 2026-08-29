"""历史记录服务测试——依赖本地 PostgreSQL（conversations/messages 落库）。

用例 ID 用 uuid4 hex（32 字符）保证每次运行新增独立会话/回合，测试幂等。
账号关联：回合归属一个测试账号（无外键，任意 uuid 文本即可）；跨账号隔离
另见 test_auth.py。
"""

import uuid
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from app.catalog.assistant_catalog import AssistantCatalog
from app.catalog.models import AssistantTarget, TargetType
from app.config.loader import MCPRegistry
from app.config.settings import Settings
from app.db.engine import Database
from app.db.models import Conversation, Message
from app.errors.base import NotFoundError
from app.registry.registry import AgentRegistry
from app.schemas.conversations import ConversationStatus, MessageStatus, TurnRecord, TurnUsage
from app.services.conversations import ConversationService

_DATABASE = Database(Settings(_env_file=None))
_ACCOUNT_ID = str(uuid.uuid4())

_FINDER_AGENT_MD = """\
---
agent_id: finder
display_name: 客户发现
version: 1.0.0
description: 发现潜在客户
default_skill: research
skills:
  - research
---
"""
_FINDER_SKILL_MD = """\
---
skill_id: research
version: 1.0.0
description: 客户调研
---
"""


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _dispose_database() -> None:
    yield
    await _DATABASE.dispose()


def _service() -> ConversationService:
    """空目录 catalog：不测 resolve 的历史用例。"""
    settings = Settings(_env_file=None)
    registry = AgentRegistry(settings, MCPRegistry(servers=[]))
    return ConversationService(_DATABASE, settings, AssistantCatalog(registry))


async def _finder_service(tmp_path: Path) -> ConversationService:
    """含 finder 专家的 catalog：resolve 绑定用例。"""
    agent_dir = tmp_path / "agents" / "finder"
    (agent_dir / "research").mkdir(parents=True)
    (agent_dir / "AGENT.md").write_text(_FINDER_AGENT_MD, encoding="utf-8")
    (agent_dir / "research" / "SKILL.md").write_text(_FINDER_SKILL_MD, encoding="utf-8")
    settings = Settings(_env_file=None, agents_root_dir=tmp_path / "agents")
    registry = AgentRegistry(settings, MCPRegistry(servers=[]))
    await registry.refresh()
    return ConversationService(_DATABASE, settings, AssistantCatalog(registry))


def _wall(day: date, hour: int = 10) -> datetime:
    """GMT+8 墙钟时间（naive，与 local_now() 落库口径一致）。"""
    return datetime.combine(day, time(hour))


async def _insert_message(
    account_id: str,
    *,
    day: date,
    conversation_id: str,
    prompt: int = 0,
    completion: int = 0,
    total: int = 0,
    cached_read: int = 0,
    cached_write: int = 0,
) -> None:
    """直接落库一条指定日期的消息（构造逐日聚合测试数据）。"""
    async with _DATABASE.session_factory() as session:
        session.add(
            Message(
                message_id=uuid.uuid4().hex,
                conversation_id=conversation_id,
                created_by=account_id,
                query="q",
                prompt_tokens=prompt,
                completion_tokens=completion,
                total_tokens=total,
                cached_read_tokens=cached_read,
                cached_write_tokens=cached_write,
                created_at=_wall(day),
            )
        )
        await session.commit()


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
    # 读取接口不下发 token 用量与模型信息（仅落库内部审计）
    dumped = msg.model_dump()
    for hidden in (
        "provider",
        "model",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "cached_read_tokens",
        "cached_write_tokens",
    ):
        assert hidden not in dumped


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


async def test_aggregate_daily_usage_groups_by_day_and_zero_fills() -> None:
    """逐日用量：按 GMT+8 自然日归组、同会话去重、窗口外排除、零填充升序。"""
    service = _service()
    account = str(uuid.uuid4())
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    cid = uuid.uuid4().hex
    await _insert_message(
        account,
        day=today,
        conversation_id=cid,
        prompt=10,
        completion=5,
        total=15,
        cached_read=3,
        cached_write=1,
    )
    await _insert_message(
        account,
        day=today,
        conversation_id=cid,
        prompt=20,
        completion=10,
        total=30,
        cached_read=6,
        cached_write=2,
    )
    await _insert_message(
        account,
        day=today - timedelta(days=1),
        conversation_id=uuid.uuid4().hex,
        prompt=100,
        completion=50,
        total=150,
    )
    await _insert_message(
        account,
        day=today - timedelta(days=10),
        conversation_id=uuid.uuid4().hex,
        total=999,
    )

    items = await service.aggregate_daily_usage(account, days=7)
    assert len(items) == 7
    assert [i.date for i in items] == [
        today - timedelta(days=offset) for offset in range(6, -1, -1)
    ]
    today_item = items[-1]
    assert today_item.conversation_count == 1  # 同一会话两条消息去重
    assert today_item.message_count == 2
    assert today_item.total_tokens == 45
    assert today_item.cached_read_tokens == 9
    assert today_item.cached_write_tokens == 3
    yesterday = next(i for i in items if i.date == today - timedelta(days=1))
    assert yesterday.message_count == 1
    assert yesterday.total_tokens == 150
    # 其余天零填充；10 天前在 7 天窗口外不计
    for item in items:
        if item.date not in (today, today - timedelta(days=1)):
            assert item.message_count == 0
            assert item.total_tokens == 0
    # 其他账号不受影响
    assert all(
        i.message_count == 0 for i in await service.aggregate_daily_usage(str(uuid.uuid4()), days=7)
    )


async def test_aggregate_daily_usage_window_and_days() -> None:
    """days 控制窗口：起点 = 今天 - days + 1，窗口外消息不计。"""
    service = _service()
    account = str(uuid.uuid4())
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    await _insert_message(
        account,
        day=today - timedelta(days=40),
        conversation_id=uuid.uuid4().hex,
        total=1,
    )

    items30 = await service.aggregate_daily_usage(account, days=30)
    assert len(items30) == 30
    assert items30[0].date == today - timedelta(days=29)
    assert all(i.total_tokens == 0 for i in items30)  # 40 天前在 30 天窗口外

    items90 = await service.aggregate_daily_usage(account, days=90)
    assert len(items90) == 90
    assert items90[0].date == today - timedelta(days=89)
    assert next(i for i in items90 if i.date == today - timedelta(days=40)).total_tokens == 1


# ---- 对话记录生命周期（resolve）----
async def test_resolve_creates_row_with_binding(tmp_path: Path) -> None:
    """空 conversation_id 建行：标题取首查截断、绑定落 agent_id。"""
    service = await _finder_service(tmp_path)
    session = await service.resolve(
        account_id=_ACCOUNT_ID, conversation_id="", agent_id="finder", query="帮我找客户"
    )
    assert session.conversation_id
    assert session.account_id == _ACCOUNT_ID
    assert session.assistant_target == AssistantTarget(type=TargetType.EXPERT, id="finder")
    assert session.assistant_meta == {"type": "expert", "id": "finder"}
    assert session.agent_id_label == "finder"
    convos = await service.list_conversations(_ACCOUNT_ID, limit=50, offset=0)
    convo = next(c for c in convos if c.conversation_id == session.conversation_id)
    assert convo.name == "帮我找客户"
    assert convo.agent_id == "finder"


async def test_resolve_generic_binding(tmp_path: Path) -> None:
    """agent_id=generic（保留字）→ 通用目标，行绑定为空。"""
    service = await _finder_service(tmp_path)
    session = await service.resolve(
        account_id=_ACCOUNT_ID, conversation_id="", agent_id="generic", query="你好"
    )
    assert session.assistant_target == AssistantTarget(type=TargetType.GENERIC)
    assert session.assistant_meta == {"type": "generic", "id": None}
    convos = await service.list_conversations(_ACCOUNT_ID, limit=50, offset=0)
    convo = next(c for c in convos if c.conversation_id == session.conversation_id)
    assert convo.agent_id is None


async def test_resolve_unknown_agent_raises_404(tmp_path: Path) -> None:
    """目录外 agent_id → NotFoundError（先于 DB 操作）。"""
    service = await _finder_service(tmp_path)
    try:
        await service.resolve(
            account_id=_ACCOUNT_ID, conversation_id="", agent_id="nope", query="hi"
        )
        raised = False
    except NotFoundError:
        raised = True
    assert raised is True


async def test_resolve_continuation_preserves_binding_and_title(tmp_path: Path) -> None:
    """续聊（空 agent_id）：沿用既有绑定与标题，不重建。"""
    service = await _finder_service(tmp_path)
    first = await service.resolve(
        account_id=_ACCOUNT_ID, conversation_id="", agent_id="finder", query="第一问"
    )
    second = await service.resolve(
        account_id=_ACCOUNT_ID,
        conversation_id=first.conversation_id,
        agent_id="",
        query="第二问",
    )
    assert second.assistant_target == first.assistant_target
    convos = await service.list_conversations(_ACCOUNT_ID, limit=50, offset=0)
    convo = next(c for c in convos if c.conversation_id == first.conversation_id)
    assert convo.name == "第一问"  # 标题保留，续聊不覆盖
    assert convo.agent_id == "finder"


async def test_resolve_rebind_switches_to_generic(tmp_path: Path) -> None:
    """续聊携带 agent_id=generic → 解除专家绑定。"""
    service = await _finder_service(tmp_path)
    first = await service.resolve(
        account_id=_ACCOUNT_ID, conversation_id="", agent_id="finder", query="hi"
    )
    second = await service.resolve(
        account_id=_ACCOUNT_ID,
        conversation_id=first.conversation_id,
        agent_id="generic",
        query="hi",
    )
    assert second.assistant_target == AssistantTarget(type=TargetType.GENERIC)
    convos = await service.list_conversations(_ACCOUNT_ID, limit=50, offset=0)
    convo = next(c for c in convos if c.conversation_id == first.conversation_id)
    assert convo.agent_id is None


async def test_resolve_cross_account_continuation_404(tmp_path: Path) -> None:
    """A 创建的会话，B 续聊 → NotFoundError（跨账号隔离）。"""
    service = await _finder_service(tmp_path)
    first = await service.resolve(
        account_id=_ACCOUNT_ID, conversation_id="", agent_id="", query="A 的会话"
    )
    other = str(uuid.uuid4())
    try:
        await service.resolve(
            account_id=other, conversation_id=first.conversation_id, agent_id="", query="hi"
        )
        raised = False
    except NotFoundError:
        raised = True
    assert raised is True


# ---- 会话记忆 L1（get_history_messages：模型上下文恢复）----
async def test_get_history_messages_returns_user_assistant_pairs() -> None:
    """历史还原为 user(query)/assistant(answer) 消息对，thinking 不进上下文。"""
    service = _service()
    cid = uuid.uuid4().hex
    await service.record_turn(
        cid,
        TurnRecord(
            message_id=uuid.uuid4().hex,
            query="找潜在客户",
            answer="已找到 5 家",
            thinking="审计内容不进模型上下文",
            account_id=_ACCOUNT_ID,
        ),
    )
    hist = await service.get_history_messages(_ACCOUNT_ID, cid, limit=50)
    assert [(m.role, m.content) for m in hist] == [
        ("user", "找潜在客户"),
        ("assistant", "已找到 5 家"),
    ]


async def test_get_history_messages_error_turn_keeps_query_only() -> None:
    """错误回合（answer 为空）：只产出 user 消息，不产出 assistant。"""
    service = _service()
    cid = uuid.uuid4().hex
    await service.record_turn(
        cid,
        TurnRecord(
            message_id=uuid.uuid4().hex,
            query="会报错",
            status=MessageStatus.ERROR,
            error="限流",
            account_id=_ACCOUNT_ID,
        ),
    )
    hist = await service.get_history_messages(_ACCOUNT_ID, cid, limit=50)
    assert [(m.role, m.content) for m in hist] == [("user", "会报错")]


async def test_get_history_messages_takes_most_recent_limit() -> None:
    """取最近 limit 条且按时间升序返回（desc 取数后反转，非最旧 N 条）。"""
    service = _service()
    cid = uuid.uuid4().hex
    base = datetime.now()
    for i in range(3):
        async with _DATABASE.session_factory() as session:
            session.add(
                Message(
                    message_id=uuid.uuid4().hex,
                    conversation_id=cid,
                    created_by=_ACCOUNT_ID,
                    query=f"问题{i}",
                    answer=f"回答{i}",
                    created_at=base + timedelta(seconds=i),
                )
            )
            await session.commit()
    hist = await service.get_history_messages(_ACCOUNT_ID, cid, limit=2)
    assert [(m.role, m.content) for m in hist] == [
        ("user", "问题1"),
        ("assistant", "回答1"),
        ("user", "问题2"),
        ("assistant", "回答2"),
    ]


async def test_get_history_messages_cross_account_404() -> None:
    """跨账号读历史上下文 → NotFoundError（与 get_messages 同源隔离）。"""
    service = _service()
    cid = uuid.uuid4().hex
    await service.record_turn(
        cid,
        TurnRecord(message_id=uuid.uuid4().hex, query="A 的历史", account_id=_ACCOUNT_ID),
    )
    with pytest.raises(NotFoundError):
        await service.get_history_messages(str(uuid.uuid4()), cid, limit=50)
