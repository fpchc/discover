"""ContextAssembler 装配测试（agent-context-plane-spec §5.1 / §6.1 / §6.3）。

覆盖：历史加载、条数与字符双预算裁剪、摘要来源追踪、附件按需读取、
端口缺失时的降级。全部 Fake Port，无网络无 DB（CLAUDE.md §12）。
"""

from __future__ import annotations

from types import SimpleNamespace

from app.application.chat.turn_context import TurnContextRequest, build_turn_context
from app.application.dto.conversations import ConversationSession
from app.config.settings import Settings
from app.environment.context import (
    ContextAssemblyOptions,
    ContextIdentity,
    ContextMessage,
    CurrentInput,
    FileRef,
)
from app.harness.context import ContextAssembler


class _FakeConversation:
    """会话历史端口 Fake：按 limit 返回最近 N 条并记录调用参数。"""

    def __init__(self, messages: list[ContextMessage]) -> None:
        self._messages = messages
        self.limits: list[int] = []

    async def load_recent_messages(
        self, *, account_id: str, conversation_id: str, limit: int
    ) -> list[ContextMessage]:
        self.limits.append(limit)
        return self._messages[-limit:]


class _FakeAttachments:
    """附件端口 Fake：记录 file_ids 并返回固定引用。"""

    def __init__(self, files: list[FileRef]) -> None:
        self._files = files
        self.calls: list[list[str]] = []

    async def load_message_attachments(
        self, *, account_id: str, conversation_id: str, file_ids: list[str]
    ) -> list[FileRef]:
        self.calls.append(list(file_ids))
        return self._files


def _history(count: int, *, size: int = 1) -> list[ContextMessage]:
    return [
        ContextMessage(
            role="user",
            content=f"消息{index}" * size,
            message_id=f"m{index}",
            source_ref="conversation:conv-1",
        )
        for index in range(count)
    ]


def _identity() -> ContextIdentity:
    return ContextIdentity(run_id="run-1", conversation_id="conv-1", account_id="acc-1")


async def test_assemble_loads_history_and_records_sources() -> None:
    port = _FakeConversation(_history(3))
    assembler = ContextAssembler(conversation=port)

    context = await assembler.assemble(_identity(), CurrentInput(text="找客户"))

    assert [message.content for message in context.conversation.recent_messages] == [
        "消息0",
        "消息1",
        "消息2",
    ]
    assert context.conversation.message_refs == ["conversation:conv-1"]
    assert context.conversation.covered_message_range == "m0..m2"
    assert context.current_input.text == "找客户"
    assert context.version == 1


async def test_assemble_without_ports_degrades_to_empty_context() -> None:
    context = await ContextAssembler().assemble(_identity(), CurrentInput(text="嗨"))

    assert context.conversation.recent_messages == []
    assert context.conversation.summary is None
    assert context.attachments.files == []


async def test_trim_keeps_only_most_recent_messages() -> None:
    port = _FakeConversation(_history(20))
    assembler = ContextAssembler(
        conversation=port, options=ContextAssemblyOptions(max_recent_messages=3, summarize=False)
    )

    context = await assembler.assemble(_identity(), CurrentInput(text="找客户"))

    assert [message.content for message in context.conversation.recent_messages] == [
        "消息17",
        "消息18",
        "消息19",
    ]
    assert port.limits == [3]


async def test_char_budget_drops_older_messages_deterministically() -> None:
    messages = [
        ContextMessage(role="user", content="a" * 10),
        ContextMessage(role="assistant", content="b" * 10),
        ContextMessage(role="user", content="c" * 10),
    ]
    assembler = ContextAssembler(
        conversation=_FakeConversation(messages),
        options=ContextAssemblyOptions(
            max_recent_messages=10, max_context_chars=25, summarize=False
        ),
    )

    context = await assembler.assemble(_identity(), CurrentInput(text="找客户"))

    # 预算 25：保留最近两条（10+10），更早一条整条丢弃
    assert [message.content for message in context.conversation.recent_messages] == [
        "b" * 10,
        "c" * 10,
    ]


async def test_single_oversized_message_is_truncated_and_marked() -> None:
    oversized = ContextMessage(role="user", content="x" * 100, message_id="m9")
    assembler = ContextAssembler(
        conversation=_FakeConversation([oversized]),
        options=ContextAssemblyOptions(
            max_recent_messages=10, max_context_chars=20, summarize=False
        ),
    )

    context = await assembler.assemble(_identity(), CurrentInput(text="找客户"))

    kept = context.conversation.recent_messages
    assert len(kept) == 1
    assert kept[0].metadata.get("truncated") is True
    assert len(kept[0].content) < 100


async def test_summary_records_source_range_and_version() -> None:
    port = _FakeConversation(_history(20))
    assembler = ContextAssembler(
        conversation=port,
        options=ContextAssemblyOptions(
            max_recent_messages=20, summarize=True, max_summary_messages=3
        ),
    )

    context = await assembler.assemble(_identity(), CurrentInput(text="找客户"))

    summary = context.conversation.summary
    assert summary is not None
    assert "消息19" in summary.summary
    assert "消息0" not in summary.summary
    assert summary.source == "conversation"
    assert summary.covered_message_ids == ["m17", "m18", "m19"]
    assert summary.covered_message_range == "m17..m19"
    assert summary.context_version == 1


async def test_attachments_loaded_only_when_file_ids_declared() -> None:
    attachments = _FakeAttachments([FileRef(file_id="f1", name="名单.xlsx")])
    assembler = ContextAssembler(conversation=_FakeConversation([]), attachments=attachments)

    without_files = await assembler.assemble(_identity(), CurrentInput(text="找客户"))
    assert without_files.attachments.files == []
    assert attachments.calls == []

    declared = await assembler.assemble(_identity(), CurrentInput(text="看附件", file_ids=["f1"]))
    assert [file.file_id for file in declared.attachments.files] == ["f1"]
    assert attachments.calls == [["f1"]]


class _UnexpectedAssembler:
    async def assemble(self, *args: object, **kwargs: object) -> object:
        raise AssertionError("debug 模式不应访问持久化会话历史")


async def test_turn_context_can_disable_history_for_debug_session() -> None:
    services = SimpleNamespace(
        settings=Settings(_env_file=None),
        context_assembler=_UnexpectedAssembler(),
    )
    request = TurnContextRequest(
        session=ConversationSession(conversation_id="debug-session", account_id="account"),
        user_input="找客户",
        run_id="run",
        phase_instance_id="example-skill",
        expert=True,
        load_history=False,
    )

    turn = await build_turn_context(services, request)  # type: ignore[arg-type]

    assert turn.context.conversation.recent_messages == []
    assert turn.context.current_input.text == "找客户"
