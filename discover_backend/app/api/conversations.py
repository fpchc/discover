"""会话接口（L4，controller）：/conversations 列表 / 消息 / 删除。

会话/回合只读检索供控制台/前端消费；删除为**软删除**（标记 is_delete=true，
保留行与 token 记录，仅从列表隐藏），并释放内存会话与运行时。
读取与删除方法不降级——DB 不可用时经中间件走统一错误响应（读不到该报错，
删不到也该报错）。
"""

from fastapi import APIRouter, Depends, Query

from app.auth.deps import get_current_account_id
from app.container import AppServices, get_services
from app.conversations.models import ConversationRecord, MessageRecord
from app.conversations.service import ConversationService
from app.errors.base import NotFoundError

router = APIRouter(prefix="/conversations", tags=["conversations"])

_PAGE_LIMIT_MAX = 200


@router.get("")
async def list_conversations(
    limit: int = Query(default=50, ge=1, le=_PAGE_LIMIT_MAX),
    offset: int = Query(default=0, ge=0),
    account_id: str = Depends(get_current_account_id),
    services: AppServices = Depends(get_services),
) -> list[ConversationRecord]:
    """分页列出当前账号会话（按 updated_at 倒序，跨账号隔离）。"""
    history = _require_history(services)
    return await history.list_conversations(account_id, limit=limit, offset=offset)


@router.get("/{conversation_id}/messages")
async def get_messages(
    conversation_id: str,
    limit: int = Query(default=50, ge=1, le=_PAGE_LIMIT_MAX),
    offset: int = Query(default=0, ge=0),
    account_id: str = Depends(get_current_account_id),
    services: AppServices = Depends(get_services),
) -> list[MessageRecord]:
    """分页列出会话消息（按 created_at 升序；非本人会话 → 404）。"""
    history = _require_history(services)
    return await history.get_messages(account_id, conversation_id, limit=limit, offset=offset)


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: str,
    account_id: str = Depends(get_current_account_id),
    services: AppServices = Depends(get_services),
) -> None:
    """删除会话（软删除）：标记 is_delete=true 并释放内存会话/运行时；皆无 → 404。

    行与 messages 保留（token 用量可审计），仅从列表隐藏且不可续聊；业务状态
    status 不被覆盖（可还原），删除仅置 is_delete 标记。非本人会话同样 404。
    """
    history = _require_history(services)
    assert services.sessions is not None
    existed_db = await history.soft_delete_conversation(account_id, conversation_id)
    existed_memory = services.sessions.delete_session(conversation_id)
    await services.discard_runtime(conversation_id)
    if not existed_db and not existed_memory:
        raise NotFoundError(f"未知会话：{conversation_id}")


def _require_history(services: AppServices) -> ConversationService:
    assert services.history is not None
    return services.history
