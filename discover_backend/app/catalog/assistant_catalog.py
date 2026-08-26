"""助手目录：聚合专家 + 内置通用项，供选择器渲染与 wire 校验。

目录接口是「用户可选助手清单」（聚合入口），不是 agents/ 目录的直接暴露。
专家来自注册表索引，通用是内置合成项；capabilities 取专家的技能 ID 列表。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.catalog.models import GENERIC_ASSISTANT_ID, GENERIC_ASSISTANT_NAME, TargetType
from app.registry.registry import AgentRegistry


class AssistantCatalogEntry(BaseModel):
    """目录条目：选择器渲染所需的最小契约。"""

    id: str
    type: TargetType
    name: str
    description: str
    capabilities: list[str] = Field(default_factory=list)


class AssistantCatalog:
    """只读助手目录。基于注册表当前索引（热重载后即最新）。"""

    def __init__(self, registry: AgentRegistry) -> None:
        self._registry = registry

    def list(self) -> list[AssistantCatalogEntry]:
        """专家（registry 索引）+ 内置通用项。"""
        entries: list[AssistantCatalogEntry] = []
        for agent_id, agent in self._registry.index().agents.items():
            package = self._registry.get_agent(agent_id)
            capabilities = list(package.manifest.skills) if package is not None else []
            entries.append(
                AssistantCatalogEntry(
                    id=agent_id,
                    type=TargetType.EXPERT,
                    name=agent.display_name,
                    description=agent.description,
                    capabilities=capabilities,
                )
            )
        entries.append(self._generic_entry())
        return entries

    def resolve(self, assistant_id: str) -> AssistantCatalogEntry | None:
        """按 id 查目录（wire 校验用）。未知 id → None。"""
        return next((entry for entry in self.list() if entry.id == assistant_id), None)

    @staticmethod
    def _generic_entry() -> AssistantCatalogEntry:
        return AssistantCatalogEntry(
            id=GENERIC_ASSISTANT_ID,
            type=TargetType.GENERIC,
            name=GENERIC_ASSISTANT_NAME,
            description="日常问答与通用助手，不绑定专家能力",
        )
