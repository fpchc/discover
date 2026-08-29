"""模型上下文组装（会话记忆 L1 + §5 上下文裁剪）：runtime 依赖的薄抽象 + 纯函数。

单一动机：为图运行时构建「发给 LLM 的消息列表」。三个关注点收敛于此——
历史恢复（fresh runtime 从 DB 回填）、顺序归一（system 前置）、预算裁剪
（超预算丢最老 assistant/tool）。Runtime 只依赖 HistoryProvider 薄协议
（结构匹配 ConversationService.get_history_messages），不引入会话服务完整接口
（CLAUDE.md §6 ISP/DIP）；历史恢复失败仅记日志降级为空（舱壁）。
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Protocol

from app.llm.models import ChatMessage


class HistoryProvider(Protocol):
    """历史上下文提供者：按账号+会话返回 role 化消息（供模型上下文恢复）。"""

    async def get_history_messages(
        self, *, account_id: str, conversation_id: str, limit: int
    ) -> list[ChatMessage]: ...


async def load_seed_history(
    provider: HistoryProvider | None,
    *,
    account_id: str,
    conversation_id: str,
    limit: int,
    logger: logging.Logger,
) -> list[ChatMessage]:
    """fresh runtime 首轮从 DB 恢复历史；失败仅记日志返回空（舱壁降级）。

    provider 为 None（测试/未接入）时直接返回空，不抛错。
    """
    if provider is None:
        return []
    try:
        return await provider.get_history_messages(
            account_id=account_id, conversation_id=conversation_id, limit=limit
        )
    except Exception as exc:
        logger.warning("历史上下文恢复失败（降级为空）：%s：%r", conversation_id, exc)
        return []


async def seed_for_turn(
    base_messages: list[ChatMessage],
    provider: HistoryProvider | None,
    *,
    account_id: str,
    conversation_id: str,
    limit: int,
    user_message: ChatMessage,
    logger: logging.Logger,
) -> list[ChatMessage]:
    """组装单轮种子消息：沿用内存历史 + 当前用户消息。

    内存历史为空（Runtime 新建/进程重启）时从 DB 恢复历史再追加用户消息，
    恢复失败降级为空（舱壁）；内存非空（续聊同 runtime）仅追加用户消息。
    """
    if base_messages:
        return [*base_messages, user_message]
    history = await load_seed_history(
        provider,
        account_id=account_id,
        conversation_id=conversation_id,
        limit=limit,
        logger=logger,
    )
    return [*history, user_message]


def system_first(messages: Sequence[ChatMessage]) -> list[ChatMessage]:
    """system 消息前置到对话头（LLM 惯例），返回新列表；空或已前置则原样返回。

    图内 messages 经 assemble 用 append reducer 把 system 追加到末尾，本函数在
    请求构造前归一为 [system, history..., user] 顺序；仅重排，不修改原列表。
    """
    if not messages:
        return []
    if messages[0].role == "system":
        return list(messages)
    systems = [m for m in messages if m.role == "system"]
    rest = [m for m in messages if m.role != "system"]
    return [*systems, *rest]


def estimate_tokens(messages: Sequence[ChatMessage]) -> int:
    """粗略 token 估算：以字符数为代理（CJK 近似 1 token/字符）。"""
    return sum(len(message.content or "") for message in messages)


def trim_context(messages: list[ChatMessage], budget: int) -> list[ChatMessage]:
    """上下文预算裁剪（§5）：超预算时从最老的助手/工具消息开始裁（保留 system/user）。"""
    result = list(messages)
    while result and estimate_tokens(result) > budget:
        candidates = [i for i, m in enumerate(result) if m.role in ("assistant", "tool")]
        if not candidates:
            break
        del result[candidates[0]]
    return result
