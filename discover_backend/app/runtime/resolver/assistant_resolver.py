"""助手解析层（graph-runtime-spec §4）：读用户显式选择，不做 LLM 路由。

接口层保留（Protocol）：未来 Policy / Workflow resolver 可插入解析链。
当前实现 ExplicitSelectionResolver：读会话绑定的 assistant_target。
"""

from __future__ import annotations

from typing import Protocol

from app.catalog.models import AssistantTarget
from app.session.models import SessionRecord


class AssistantResolver(Protocol):
    """助手解析接口：输入会话，输出目标；无目标 → None（走通用对话）。"""

    def resolve(self, session: SessionRecord) -> AssistantTarget | None: ...


class ExplicitSelectionResolver:
    """用户显式选择：直接读会话绑定的 assistant_target。"""

    def resolve(self, session: SessionRecord) -> AssistantTarget | None:
        return session.assistant_target
