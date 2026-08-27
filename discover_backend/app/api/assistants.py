"""助手目录接口（L4，controller）：GET /assistants。

只读目录（专家），供选择器渲染；非 agents/ 管理接口。
通用对话是未指定 agent_id 时的默认态，不列入目录。
聚合逻辑在 catalog 层，本文件只做参数提取与转调。
"""

from fastapi import APIRouter, Depends

from app.catalog.assistant_catalog import AssistantCatalogEntry
from app.container import AppServices, get_services

router = APIRouter(tags=["assistants"])


@router.get("/assistants")
async def list_assistants(
    services: AppServices = Depends(get_services),
) -> list[AssistantCatalogEntry]:
    """列出用户可选助手：专家；通用对话为默认态，不列入目录。"""
    return services.assistant_catalog().list()
