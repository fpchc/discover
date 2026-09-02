"""助手解析层（graph-runtime-spec §4）：读用户显式选择，不做 LLM 路由。

接口层保留（Protocol）：未来 Policy / Workflow resolver 可插入解析链。
当前实现 ExplicitSelectionResolver：直接透传对话记录绑定的 assistant_target
（由 ConversationService.resolve 落库后经路由进入图状态）。
"""

from __future__ import annotations

from typing import Protocol

from app.domain.assistant.models import AssistantTarget


class AssistantResolver(Protocol):
    """助手解析接口：输入绑定目标，输出目标；无目标 → None（走通用对话）。"""

    def resolve(self, binding: AssistantTarget | None) -> AssistantTarget | None: ...


class ExplicitSelectionResolver:
    """用户显式选择：直接返回对话记录绑定的 assistant_target。"""

    def resolve(self, binding: AssistantTarget | None) -> AssistantTarget | None:
        return binding
