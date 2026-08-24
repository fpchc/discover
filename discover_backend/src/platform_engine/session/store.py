"""会话注册表（L1，内存态）。

会话记录为进程内注册表。变更操作在事件循环内同步完成（读-改-写之间
无 await 间隙），因此无需加锁。
"""

import uuid

from platform_engine.errors.base import SessionNotFoundError
from platform_engine.session.models import SessionRecord, utc_now


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

    def bind_agent(self, session_id: str, agent_id: str) -> SessionRecord:
        """会话内绑定智能体（一级路由命中后调用，防重入一级路由）。"""
        current = self.get(session_id)
        updated = current.model_copy(update={"agent_id": agent_id, "updated_at": utc_now()})
        self._sessions[session_id] = updated
        return updated

    def remove(self, session_id: str) -> SessionRecord:
        """移除会话记录。"""
        record = self._sessions.pop(session_id, None)
        if record is None:
            raise SessionNotFoundError(f"未知会话：{session_id}")
        return record
