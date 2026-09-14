"""技能包调试纯函数单测（工具名解析，无网络 / 无 DB）。"""

from __future__ import annotations

import pytest
from app.application.skill_package.debug import resolve_smoke_tool
from app.environment.tools.models import ToolDescriptor, ToolSource
from app.shared.errors.base import BadRequestError, NotFoundError


class _FakeCatalog:
    def __init__(self, names: list[str], descriptor: ToolDescriptor | None = None) -> None:
        self._names = names
        self._descriptor = descriptor

    def get_descriptor(self, qualified_name: str) -> ToolDescriptor | None:
        del qualified_name
        return self._descriptor

    def catalog_tool_names(self) -> list[str]:
        return self._names


def test_resolve_qualified_name_direct() -> None:
    descriptor = ToolDescriptor(
        qualified_name="a.b.script.calc",
        short_name="calc",
        namespace="a.b.script",
        description="",
        parameters={},
        source=ToolSource.SCRIPT,
        tier=1,
    )
    catalog = _FakeCatalog(["a.b.script.calc"], descriptor=descriptor)

    assert resolve_smoke_tool(catalog, "a.b.script.calc") == "a.b.script.calc"


def test_resolve_short_name_unique() -> None:
    catalog = _FakeCatalog(["a.b.script.calc", "x.y.mcp.search"])

    assert resolve_smoke_tool(catalog, "search") == "x.y.mcp.search"


def test_resolve_short_name_ambiguous() -> None:
    catalog = _FakeCatalog(["a.b.script.calc", "x.y.mcp.calc"])

    with pytest.raises(BadRequestError):
        resolve_smoke_tool(catalog, "calc")


def test_resolve_missing() -> None:
    catalog = _FakeCatalog(["a.b.script.calc"])

    with pytest.raises(NotFoundError):
        resolve_smoke_tool(catalog, "unknown")
