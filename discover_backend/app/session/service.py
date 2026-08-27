"""会话门面（L1）：把工作区、注册表、文件服务编排为会话生命周期操作。

接入层（L4）只面向 SessionService，不直接触碰文件系统与数据库内部。
文件注册表多消费方共享、不强绑定会话/智能体（用户决策）；预览路由按
file_id 生成（/files/{file_id}/preview）。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

from app.catalog.models import AssistantTarget
from app.config.settings import Settings
from app.db.engine import Database
from app.extensions.storage.base_storage import BaseStorage
from app.schemas.files import FileResponse
from app.session.files import FileService
from app.session.models import ArtifactRecord, SessionRecord
from app.session.store import SessionStore
from app.session.workspace import Workspace, WorkspaceManager


def file_preview_path(record: ArtifactRecord) -> str:
    """文件预览路由（相对路径；接入层按同一模式挂载，不硬编码主机）。

    注册表全局可预览（凭 file_id，uuid4 hex 不可猜测），无会话归属段。
    """
    return f"/files/{record.artifact_id}/preview"


class SessionService:
    """会话生命周期唯一入口：创建 / 查询 / 绑定 / 清理 / 文件。"""

    def __init__(self, settings: Settings, db: Database, storage: BaseStorage) -> None:
        self._store = SessionStore()
        self._workspaces = WorkspaceManager(settings)
        self._files = FileService(settings, db, storage)

    # ---- 会话生命周期 ----
    async def create_session(self) -> SessionRecord:
        """建会话：仅注册记录（工作区按智能体键控，不再建会话目录）。"""
        return self._store.create_session()

    def get_session(self, session_id: str) -> SessionRecord:
        return self._store.get(session_id)

    def bind_assistant(self, session_id: str, target: AssistantTarget) -> SessionRecord:
        return self._store.bind_assistant(session_id, target)

    def delete_session(self, session_id: str) -> bool:
        """移除内存会话；不存在返回 False。"""
        return self._store.delete(session_id)

    # ---- 工作区 ----
    async def workspace_for(self, agent_id: str) -> Workspace:
        """返回（必要时创建）智能体工作区（按 agent 键控，跨会话共享）。"""
        return await self._workspaces.create(agent_id)

    # ---- 工具产物登记 ----
    async def register_artifact(
        self,
        *,
        source_path: Path,
        filename: str,
    ) -> ArtifactRecord:
        """登记工具产物（源文件须为普通文件；注册表全局共享）。"""
        return await self._files.register(source_path=source_path, filename=filename)

    # ---- 文件上传 / 预览 ----
    async def upload_file(
        self,
        *,
        filename: str,
        content: bytes,
        mimetype: str,
    ) -> FileResponse:
        """上传文件（用户上传，字节入存储层，used=false 待消费）。"""
        return await self._files.upload(filename=filename, content=content, mimetype=mimetype)

    async def resolve_preview(self, file_id: str) -> tuple[AsyncIterator[bytes], str, str]:
        """解析文件预览：字节流 + media_type + 原始文件名；不存在抛 404。

        预览即标记 used（best-effort，供后续清理）。
        """
        return await self._files.get_content_stream_by_id(file_id)
