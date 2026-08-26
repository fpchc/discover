"""技能解析层（graph-runtime-spec §4）：确定性策略链，不做 LLM 识别。

策略链依序尝试，首个命中返回：显式技能 → 默认技能 → 唯一技能 → 首个技能。
未来追加权限 / 上下文感知策略，追加进策略链即可，不改核心流程。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class SkillResolutionContext:
    """技能解析上下文：可用技能 + 默认技能 + 用户显式技能。"""

    # pragma: 简化 — 纯内部不可变值对象，不跨边界序列化，无需 pydantic

    skill_ids: tuple[str, ...]
    default_skill: str | None = None
    explicit_skill: str | None = None


class SkillStrategy(Protocol):
    """单个选技能策略：命中返回 skill_id，否则 None（交给下一策略）。"""

    def resolve(self, context: SkillResolutionContext) -> str | None: ...


class ExplicitSkillStrategy:
    """用户显式指定技能（未来：session.skill_id）。"""

    def resolve(self, context: SkillResolutionContext) -> str | None:
        if context.explicit_skill is not None and context.explicit_skill in context.skill_ids:
            return context.explicit_skill
        return None


class DefaultSkillStrategy:
    """智能体声明了默认技能且可用。"""

    def resolve(self, context: SkillResolutionContext) -> str | None:
        if context.default_skill is not None and context.default_skill in context.skill_ids:
            return context.default_skill
        return None


class SingleSkillStrategy:
    """仅有一个技能时直接选中。"""

    def resolve(self, context: SkillResolutionContext) -> str | None:
        if len(context.skill_ids) == 1:
            return context.skill_ids[0]
        return None


class FallbackSkillStrategy:
    """兜底：取首个可用技能。"""

    def resolve(self, context: SkillResolutionContext) -> str | None:
        return context.skill_ids[0] if context.skill_ids else None


class SkillResolver:
    """确定性技能解析：策略链依序尝试，首个命中返回。"""

    def __init__(self) -> None:
        self._strategies: tuple[SkillStrategy, ...] = (
            ExplicitSkillStrategy(),
            DefaultSkillStrategy(),
            SingleSkillStrategy(),
            FallbackSkillStrategy(),
        )

    def resolve(self, context: SkillResolutionContext) -> str | None:
        for strategy in self._strategies:
            result = strategy.resolve(context)
            if result is not None:
                return result
        return None
