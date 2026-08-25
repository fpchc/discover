"""会话门面（L1）：把工作区、注册表、产物管理编排为会话生命周期操作。

接入层（L4）只面向 SessionService，不直接触碰文件系统与数据库内部。
产物下载返回归属校验后的句柄（存储键 + 记录）；下载路由在同一模块内唯一生成。
"""

from dataclasses import dataclass
from pathlib import Path

from app.config.settings import Settings
from app.db.engine import Database
from app.errors.base import SessionError
from app.session.artifacts import ArtifactManager, record_to_dto
from app.session.models import ArtifactRecord, SessionRecord
from app.session.store import SessionStore
from app.session.workspace import Workspace, WorkspaceManager, _is_within
from app.storage.base import BaseStorage


@dataclass(frozen=True)
class ArtifactDownload:
    """产物下载句柄：存储键 + 归属记录（纯内部运行句柄）。"""

    # pragma: 简化 — 内部运行句柄，不跨边界，无需 pydantic
    storage_key: str
    record: ArtifactRecord


def artifact_download_path(record: ArtifactRecord) -> str:
    """产物下载路由（相对路径；接入层按同一模式挂载，不硬编码主机）。"""
    return f"/sessions/{record.session_id}/artifacts/{record.artifact_id}"


class SessionService:
    """会话生命周期唯一入口：创建 / 查询 / 绑定 / 清理 / 产物。"""

    def __init__(self, settings: Settings, db: Database, storage: BaseStorage) -> None:
        self._store = SessionStore()
        self._workspaces = WorkspaceManager(settings)
        self._artifacts = ArtifactManager(settings, db, storage)

    # ---- 会话生命周期 ----
    async def create_session(self) -> SessionRecord:
        """建会话：仅注册记录（工作区按智能体键控，不再建会话目录）。"""
        return self._store.create_session()

    def get_session(self, session_id: str) -> SessionRecord:
        return self._store.get(session_id)

    def bind_agent(self, session_id: str, agent_id: str) -> SessionRecord:
        return self._store.bind_agent(session_id, agent_id)

    # ---- 工作区 ----
    async def workspace_for(self, agent_id: str) -> Workspace:
        """返回（必要时创建）智能体工作区（按 agent 键控，跨会话共享）。"""
        return await self._workspaces.create(agent_id)

    # ---- 产物 ----
    async def register_artifact(
        self,
        *,
        session_id: str,
        agent_id: str,
        source_path: Path,
        filename: str,
    ) -> ArtifactRecord:
        """登记会话产物（源文件须位于该智能体工作区内）。"""
        self._store.get(session_id)
        workspace = await self._workspaces.create(agent_id)
        if not _is_within(workspace.root, source_path):
            raise SessionError(f"产物不在智能体工作区内：{source_path}")
        return await self._artifacts.register(
            session_id=session_id,
            agent_id=agent_id,
            source_path=source_path,
            filename=filename,
        )

    async def resolve_download(self, session_id: str, artifact_id: str) -> ArtifactDownload | None:
        """按会话归属解析产物下载句柄；归属不符返回 None（不可枚举）。"""
        row = await self._artifacts.get(session_id, artifact_id)
        if row is None:
            return None
        return ArtifactDownload(storage_key=row.storage_key, record=record_to_dto(row))
