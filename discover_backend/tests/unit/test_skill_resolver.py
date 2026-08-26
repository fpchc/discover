"""SkillResolver 确定性策略链单元测试（graph-runtime-spec §4）。

策略顺序：显式 → 默认 → 唯一 → 首个；无技能 → None。
"""

from app.runtime.resolver.skill_resolver import SkillResolutionContext, SkillResolver


def _context(
    *,
    skills: tuple[str, ...],
    default_skill: str | None = None,
    explicit_skill: str | None = None,
) -> SkillResolutionContext:
    return SkillResolutionContext(
        skill_ids=skills,
        default_skill=default_skill,
        explicit_skill=explicit_skill,
    )


def test_explicit_strategy_takes_priority() -> None:
    resolver = SkillResolver()
    ctx = _context(skills=("a", "b"), default_skill="a", explicit_skill="b")
    assert resolver.resolve(ctx) == "b"


def test_default_strategy_when_no_explicit() -> None:
    resolver = SkillResolver()
    ctx = _context(skills=("a", "b"), default_skill="a")
    assert resolver.resolve(ctx) == "a"


def test_single_skill_selected() -> None:
    resolver = SkillResolver()
    ctx = _context(skills=("research",))
    assert resolver.resolve(ctx) == "research"


def test_fallback_to_first_skill() -> None:
    resolver = SkillResolver()
    ctx = _context(skills=("x", "y", "z"))
    assert resolver.resolve(ctx) == "x"


def test_explicit_unknown_skill_falls_through() -> None:
    resolver = SkillResolver()
    ctx = _context(skills=("a", "b"), default_skill="a", explicit_skill="nope")
    assert resolver.resolve(ctx) == "a"


def test_default_not_in_skills_falls_through() -> None:
    resolver = SkillResolver()
    ctx = _context(skills=("b",), default_skill="missing")
    assert resolver.resolve(ctx) == "b"


def test_empty_skills_returns_none() -> None:
    resolver = SkillResolver()
    ctx = _context(skills=())
    assert resolver.resolve(ctx) is None
