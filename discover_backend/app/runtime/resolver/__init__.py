"""解析层（runtime/resolver）：当前请求应选哪个助手 / 技能。

解析器服务 Runtime 的单轮解析（graph-runtime-spec §4），不构成独立业务体系；
未来追加权限 / 上下文感知策略进策略链即可。
"""

from app.runtime.resolver.assistant import AssistantResolver, ExplicitSelectionResolver
from app.runtime.resolver.skill import (
    DefaultSkillStrategy,
    ExplicitSkillStrategy,
    FallbackSkillStrategy,
    SingleSkillStrategy,
    SkillResolutionContext,
    SkillResolver,
    SkillStrategy,
)

__all__ = [
    "AssistantResolver",
    "DefaultSkillStrategy",
    "ExplicitSelectionResolver",
    "ExplicitSkillStrategy",
    "FallbackSkillStrategy",
    "SingleSkillStrategy",
    "SkillResolutionContext",
    "SkillResolver",
    "SkillStrategy",
]
