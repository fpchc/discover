"""会话注册表（L1，内存态）。

会话记录为进程内注册表。变更操作在事件循环内同步完成（读-改-写之间
无 await 间隙），因此无需加锁。
"""

import uuid

from app.catalog.models import AssistantTarget
from app.errors.base import SessionNotFoundError
from app.session.models import SessionRecord, utc_now


class SessionStore:
    """会话注册表。"""

    def __init__(self) -> None:
        self._sessions: dict[str, SessionRecord] = {}

    # ---- 会话 ----
    def create_session(self) -> SessionRecord:
        record = SessionRecord(session_id=uuid.uuid4().hex)
        self._sessions[record.session_id] = record
        return record

    def get(self, session_id: str) -> SessionRecord:
        try:
            return self._sessions[session_id]
        except KeyError as exc:
            raise SessionNotFoundError(f"未知会话：{session_id}") from exc

    def bind_assistant(self, session_id: str, target: AssistantTarget) -> SessionRecord:
        """会话内绑定助手目标（用户显式选择；切换同样走此方法）。"""
        current = self.get(session_id)
        updated = current.model_copy(update={"assistant_target": target, "updated_at": utc_now()})
        self._sessions[session_id] = updated
        return updated
