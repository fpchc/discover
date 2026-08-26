"""历史读取接口（L4，controller）。

会话/回合历史只读检索，供未来控制台/前端消费。读取方法不降级——DB 不可用时
经中间件走统一错误响应（读不到数据就该报错）。
"""

from fastapi import APIRouter, Depends, Query

from app.container import AppServices, get_services
from app.history.models import ConversationRecord, MessageRecord
from app.history.service import ConversationService

router = APIRouter(tags=["history"])

_PAGE_LIMIT_MAX = 200


@router.get("/conversations")
async def list_conversations(
    limit: int = Query(default=50, ge=1, le=_PAGE_LIMIT_MAX),
    offset: int = Query(default=0, ge=0),
    services: AppServices = Depends(get_services),
) -> list[ConversationRecord]:
    """分页列出会话（按 updated_at 倒序）。"""
    history = _require_history(services)
    return await history.list_conversations(limit=limit, offset=offset)


@router.get("/conversations/{conversation_id}/messages")
async def get_messages(
    conversation_id: str,
    limit: int = Query(default=50, ge=1, le=_PAGE_LIMIT_MAX),
    offset: int = Query(default=0, ge=0),
    services: AppServices = Depends(get_services),
) -> list[MessageRecord]:
    """分页列出会话消息（按 created_at 升序）。"""
    history = _require_history(services)
    return await history.get_messages(conversation_id, limit=limit, offset=offset)


@router.get("/conversations/{conversation_id}/usage")
async def get_usage(
    conversation_id: str,
    services: AppServices = Depends(get_services),
) -> dict[str, object]:
    """会话级用量汇总（tokens 聚合 + 消息数）。"""
    history = _require_history(services)
    return await history.get_usage(conversation_id)


def _require_history(services: AppServices) -> ConversationService:
    assert services.history is not None
    return services.history
