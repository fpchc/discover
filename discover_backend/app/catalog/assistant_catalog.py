"""助手目录：聚合专家供选择器渲染与 wire 校验。

目录接口是「用户可选助手清单」（聚合入口），不是 agents/ 目录的直接暴露。
专家来自注册表索引；通用对话是未指定 agent_id 时的默认态，不列入目录；
capabilities 取专家的技能 ID 列表。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.catalog.models import GENERIC_ASSISTANT_ID, AssistantTarget, TargetType
from app.errors.base import NotFoundError
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
        """专家（registry 索引）。通用对话为未绑定默认，不列入目录。"""
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
        return entries

    def resolve(self, assistant_id: str) -> AssistantCatalogEntry | None:
        """按 id 查目录（wire 校验用）。未知 id → None。"""
        return next((entry for entry in self.list() if entry.id == assistant_id), None)

    def resolve_target(self, agent_id: str) -> AssistantTarget | None:
        """wire agent_id → AssistantTarget；空串 → None（沿用/不绑定）；未知 → 404。

        "generic"（保留字）→ 通用对话目标；其余按目录校验，命中 → 专家目标。
        目录外 id 抛 NotFoundError（不泄露存在性，与续聊归属校验一致）。
        """
        agent_id = agent_id.strip()
        if not agent_id:
            return None
        if agent_id == GENERIC_ASSISTANT_ID:
            return AssistantTarget(type=TargetType.GENERIC)
        entry = self.resolve(agent_id)
        if entry is None:
            raise NotFoundError(f"未知助手：{agent_id}")
        return AssistantTarget(type=TargetType.EXPERT, id=entry.id)
