"""模型上下文组装（会话记忆 L1 + 上下文裁剪）纯函数与降级逻辑测试（无网络 / 无 DB）。"""

import logging
from typing import Literal

from app.llm.models import ChatMessage
from app.runtime.context import (
    estimate_tokens,
    load_seed_history,
    seed_for_turn,
    system_first,
    trim_context,
)

_LOG = logging.getLogger("test")


def _msg(role: Literal["system", "user", "assistant", "tool"], content: str) -> ChatMessage:
    return ChatMessage(role=role, content=content)


class _FakeProvider:
    """测试桩：满足 HistoryProvider 契约（结构匹配，非继承）。"""

    def __init__(self, messages: list[ChatMessage], *, error: bool = False) -> None:
        self._messages = messages
        self._error = error

    async def get_history_messages(
        self, *, account_id: str, conversation_id: str, limit: int
    ) -> list[ChatMessage]:
        del account_id, conversation_id, limit
        if self._error:
            raise RuntimeError("db down")
        return self._messages


# ---- system_first：system 前置归一 ----
def test_system_first_reorders_system_to_front() -> None:
    messages = [_msg("user", "历史问题"), _msg("system", "你是助手"), _msg("assistant", "回答")]
    result = system_first(messages)
    assert [m.role for m in result] == ["system", "user", "assistant"]
    # 原列表不被修改
    assert [m.role for m in messages] == ["user", "system", "assistant"]


def test_system_first_already_first_returns_same() -> None:
    messages = [_msg("system", "s"), _msg("user", "u")]
    assert system_first(messages) == messages


def test_system_first_empty_and_no_system() -> None:
    assert system_first([]) == []
    messages = [_msg("user", "u"), _msg("assistant", "a")]
    assert system_first(messages) == messages


# ---- seed_for_turn / load_seed_history：恢复 + 舱壁降级 ----
async def test_seed_for_turn_hydrates_from_db_when_memory_empty() -> None:
    provider = _FakeProvider([_msg("user", "旧问题"), _msg("assistant", "旧回答")])
    user = _msg("user", "新问题")
    seed = await seed_for_turn(
        [], provider, account_id="a", conversation_id="c", limit=50, user_message=user, logger=_LOG
    )
    assert [m.content for m in seed] == ["旧问题", "旧回答", "新问题"]


async def test_seed_for_turn_appends_when_memory_present() -> None:
    provider = _FakeProvider([_msg("user", "不该加载")])
    base = [_msg("user", "内存历史")]
    user = _msg("user", "新问题")
    seed = await seed_for_turn(
        base,
        provider,
        account_id="a",
        conversation_id="c",
        limit=50,
        user_message=user,
        logger=_LOG,
    )
    assert [m.content for m in seed] == ["内存历史", "新问题"]


async def test_seed_for_turn_degrades_to_empty_history_on_error() -> None:
    provider = _FakeProvider([], error=True)
    user = _msg("user", "新问题")
    seed = await seed_for_turn(
        [], provider, account_id="a", conversation_id="c", limit=50, user_message=user, logger=_LOG
    )
    assert [m.content for m in seed] == ["新问题"]


async def test_load_seed_history_none_provider_returns_empty() -> None:
    result = await load_seed_history(
        None, account_id="a", conversation_id="c", limit=50, logger=_LOG
    )
    assert result == []


# ---- trim_context：预算裁剪（保留 system/user，丢最老 assistant/tool）----
def test_trim_context_keeps_system_and_user() -> None:
    messages = [
        _msg("system", "s"),
        _msg("user", "u1"),
        _msg("assistant", "a1"),
        _msg("user", "u2"),
    ]
    result = trim_context(messages, budget=1)
    assert [m.role for m in result] == ["system", "user", "user"]


def test_trim_context_returns_untouched_within_budget() -> None:
    messages = [_msg("user", "u"), _msg("assistant", "a")]
    assert trim_context(messages, budget=1000) == messages


def test_estimate_tokens_counts_characters() -> None:
    assert estimate_tokens([_msg("user", "你好"), _msg("assistant", "hi")]) == 4
