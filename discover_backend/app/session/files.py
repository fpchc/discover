"""文件服务（L1，Blob Engine：字节入存储层，元数据入 upload_files 表）。

多消费方共享的文件注册表（agent 产物 / 用户上传 / 知识库等），不强绑定会话/
智能体（用户决策）；created_by_role 作宽松消费方标识；used 标记文件是否被使用，
供后续清理未使用文件。工具产物走 register（源文件在磁盘），用户上传走 upload
（原始字节），预览统一走 get_content_stream_by_id（按 DB record id 流式）。
CLAUDE.md §3：持久化载体为 ORM，跨边界传递用 pydantic DTO；文件读取/删除走
anyio 线程池，DB 走 async 会话，全程无阻塞（CLAUDE.md §4）。
"""

from __future__ import annotations

import hashlib
import logging
import mimetypes
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import anyio

from app.config.settings import Settings
from app.db.base import local_now
from app.db.engine import Database
from app.db.models import UploadFileRecord
from app.errors.base import BadRequestError, NotFoundError, SessionError
from app.extensions.storage.base_storage import BaseStorage
from app.schemas.files import FileResponse
from app.session.models import ArtifactRecord

logger = logging.getLogger(__name__)

_FALLBACK_MEDIA_TYPE = "application/octet-stream"
_WINDOWS_FORBIDDEN = set('<>:"/\\|?*')


def _validate_filename(filename: str) -> None:
    """文件名合法性：拒绝路径分隔符与 Windows 非法字符，防穿越与畸形名。"""
    if not filename or filename in {".", ".."}:
        raise BadRequestError(f"非法文件名：{filename!r}")
    if any(ch in _WINDOWS_FORBIDDEN or ord(ch) < 32 for ch in filename):
        raise BadRequestError(f"非法文件名：{filename!r}")
    if filename.strip() != filename:
        raise BadRequestError(f"非法文件名：{filename!r}")


def _parse_allowed_extensions(raw: str) -> list[str]:
    """逗号分隔配置 → 小写去点扩展名列表（空段忽略）。"""
    return [part.strip().lower().lstrip(".") for part in raw.split(",") if part.strip()]


def _stat_source(path: Path) -> int:
    """产物须为普通文件，返回字节数。"""
    if path.is_symlink() or not path.is_file():
        raise SessionError(f"产物不是普通文件：{path}")
    return path.stat().st_size


def _read_source(path: Path) -> bytes:
    return path.read_bytes()


def _remove_source(path: Path) -> None:
    path.unlink(missing_ok=True)


def _content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def record_to_dto(row: UploadFileRecord) -> ArtifactRecord:
    """ORM 文件记录 → 产物 DTO（工具产物事件用；仅元数据）。"""
    return ArtifactRecord(
        artifact_id=row.file_id,
        filename=row.name,
        media_type=row.media_type,
        size_bytes=row.size_bytes,
        created_at=row.created_at,
    )


def _to_file_response(row: UploadFileRecord) -> FileResponse:
    """ORM 文件记录 → 文件 API 响应 DTO。"""
    return FileResponse(
        file_id=row.file_id,
        name=row.name,
        media_type=row.media_type,
        size_bytes=row.size_bytes,
        created_at=row.created_at,
    )


class FileService:
    """文件注册表服务：登记/上传/查询/预览/使用标记。"""

    def __init__(self, settings: Settings, db: Database, storage: BaseStorage) -> None:
        self._max_artifact_bytes = settings.artifact_max_size_bytes
        self._max_upload_bytes = settings.storage_upload_file_size_limit_mb * 1024 * 1024
        self._allowed_extensions = _parse_allowed_extensions(
            settings.storage_upload_allowed_extensions
        )
        self._storage_type = settings.storage_backend
        self._db = db
        self._storage = storage

    # ---- 工具产物登记（源文件在磁盘） ----
    async def register(
        self,
        *,
        source_path: Path,
        filename: str,
        created_by_role: str = "agent",
    ) -> ArtifactRecord:
        """登记产物：源文件字节→存储层，元数据入库，清理源文件。"""
        _validate_filename(filename)
        size = await anyio.to_thread.run_sync(_stat_source, source_path)
        if size > self._max_artifact_bytes:
            raise SessionError(
                f"产物超过大小上限（{self._max_artifact_bytes} 字节）：{source_path}"
            )
        data = await anyio.to_thread.run_sync(_read_source, source_path)
        row = await self._store(
            filename=filename, data=data, mimetype="", created_by_role=created_by_role
        )
        await anyio.to_thread.run_sync(_remove_source, source_path)
        return record_to_dto(row)

    # ---- 用户上传（原始字节） ----
    async def upload(
        self,
        *,
        filename: str,
        content: bytes,
        mimetype: str,
        created_by_role: str = "user",
    ) -> FileResponse:
        """上传文件：校验大小与扩展名，字节→存储层，元数据入库。"""
        _validate_filename(filename)
        size = len(content)
        if size > self._max_upload_bytes:
            raise BadRequestError(f"文件超过大小上限（{self._max_upload_bytes} 字节）：{filename}")
        extension = Path(filename).suffix.lstrip(".").lower()
        if self._allowed_extensions and extension not in self._allowed_extensions:
            allowed = ", ".join(self._allowed_extensions)
            shown = extension or "(无扩展名)"
            raise BadRequestError(f"不允许的文件类型：.{shown}（允许：{allowed}）")
        row = await self._store(
            filename=filename, data=content, mimetype=mimetype, created_by_role=created_by_role
        )
        return _to_file_response(row)

    async def _store(
        self, *, filename: str, data: bytes, mimetype: str, created_by_role: str
    ) -> UploadFileRecord:
        """存储层落盘 + 元数据入库（register/upload 共用）。"""
        file_id = uuid.uuid4().hex
        storage_key = f"{file_id}{Path(filename).suffix}"
        await self._storage.save(storage_key, data)
        media_type = mimetype or (mimetypes.guess_type(filename)[0] or _FALLBACK_MEDIA_TYPE)
        row = UploadFileRecord(
            file_id=file_id,
            storage_type=self._storage_type,
            storage_key=storage_key,
            name=filename,
            extension=Path(filename).suffix.lstrip("."),
            media_type=media_type,
            size_bytes=len(data),
            hash=_content_hash(data),
            created_by_role=created_by_role,
        )
        async with self._db.session_factory() as session:
            session.add(row)
            await session.commit()
        return row

    # ---- 查询 / 预览 / 使用标记 ----
    async def get(self, file_id: str) -> UploadFileRecord | None:
        """按标识查询文件记录（注册表全局可查，不做归属过滤）。"""
        async with self._db.session_factory() as session:
            return await session.get(UploadFileRecord, file_id)

    async def get_content_stream_by_id(self, file_id: str) -> tuple[AsyncIterator[bytes], str, str]:
        """按 DB record id 流式返回原始文件（inline 预览）。

        Returns:
            (字节流, media_type, 原始文件名)。文件不存在抛 NotFoundError（404）。
        """
        row = await self.get(file_id)
        if row is None:
            raise NotFoundError(f"文件不存在：{file_id}")
        await self.mark_used(file_id)
        return self._storage.load_stream(row.storage_key), row.media_type, row.name

    async def mark_used(self, file_id: str) -> None:
        """标记文件已被使用（预览/下载等消费时调用）。

        best-effort：失败仅记日志，不影响预览主流程（舱壁）。
        """
        try:
            async with self._db.session_factory() as session:
                row = await session.get(UploadFileRecord, file_id)
                if row is None or row.used:
                    return
                row.used = True
                row.used_at = local_now()
                await session.commit()
        except Exception:
            logger.warning("标记文件已使用失败（best-effort 忽略）：%s", file_id)
