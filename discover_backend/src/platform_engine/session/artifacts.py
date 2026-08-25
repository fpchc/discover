"""产物登记与归属校验（Blob Engine，L1）。

产物字节流入存储层（BaseStorage，UUID 扁平无目录层级），业务元数据入
upload_files 表。CLAUDE.md §3：持久化载体为 ORM，跨边界传递用 pydantic DTO。
文件读取/删除走 anyio 线程池，DB 走 async 会话，全程无阻塞（CLAUDE.md §4）。
"""

from __future__ import annotations

import mimetypes
import uuid
from pathlib import Path

import anyio

from platform_engine.config.settings import Settings
from platform_engine.db.engine import Database
from platform_engine.db.models import UploadFileRecord
from platform_engine.errors.base import SessionError
from platform_engine.session.models import ArtifactRecord
from platform_engine.storage.base import BaseStorage

_FALLBACK_MEDIA_TYPE = "application/octet-stream"
_WINDOWS_FORBIDDEN = set('<>:"/\\|?*')


def _validate_filename(filename: str) -> None:
    """文件名合法性：拒绝路径分隔符与 Windows 非法字符，防穿越与畸形名。"""
    if not filename or filename in {".", ".."}:
        raise SessionError(f"非法产物文件名：{filename!r}")
    if any(ch in _WINDOWS_FORBIDDEN or ord(ch) < 32 for ch in filename):
        raise SessionError(f"非法产物文件名：{filename!r}")
    if filename.strip() != filename:
        raise SessionError(f"非法产物文件名：{filename!r}")


def _stat_source(path: Path) -> int:
    """产物须为普通文件，返回字节数。"""
    if path.is_symlink() or not path.is_file():
        raise SessionError(f"产物不是普通文件：{path}")
    return path.stat().st_size


def _read_source(path: Path) -> bytes:
    return path.read_bytes()


def _remove_source(path: Path) -> None:
    path.unlink(missing_ok=True)


def record_to_dto(row: UploadFileRecord) -> ArtifactRecord:
    """ORM 产物记录 → 跨边界 DTO（仅元数据，不含存储内部键）。"""
    return ArtifactRecord(
        artifact_id=row.file_id,
        session_id=row.session_id,
        agent_id=row.agent_id,
        filename=row.filename,
        media_type=row.media_type,
        size_bytes=row.size_bytes,
        created_at=row.created_at,
    )


class ArtifactManager:
    """产物管理：字节→存储层，元数据→ upload_files 表。"""

    def __init__(self, settings: Settings, db: Database, storage: BaseStorage) -> None:
        self._max_bytes = settings.artifact_max_size_bytes
        self._db = db
        self._storage = storage

    async def register(
        self,
        *,
        session_id: str,
        agent_id: str,
        source_path: Path,
        filename: str,
    ) -> ArtifactRecord:
        """登记产物：源文件字节→存储层，元数据入库，清理源文件。"""
        _validate_filename(filename)
        size = await anyio.to_thread.run_sync(_stat_source, source_path)
        if size > self._max_bytes:
            raise SessionError(f"产物超过大小上限（{self._max_bytes} 字节）：{source_path}")
        data = await anyio.to_thread.run_sync(_read_source, source_path)
        file_id = uuid.uuid4().hex
        storage_key = f"{file_id}{Path(filename).suffix}"
        await self._storage.save(storage_key, data)
        await anyio.to_thread.run_sync(_remove_source, source_path)
        media_type = mimetypes.guess_type(filename)[0] or _FALLBACK_MEDIA_TYPE
        row = UploadFileRecord(
            file_id=file_id,
            storage_key=storage_key,
            filename=filename,
            media_type=media_type,
            size_bytes=size,
            session_id=session_id,
            agent_id=agent_id,
        )
        async with self._db.session_factory() as session:
            session.add(row)
            await session.commit()
        return record_to_dto(row)

    async def get(self, session_id: str, file_id: str) -> UploadFileRecord | None:
        """按会话归属查询产物记录；归属不符视为不存在（不可枚举）。"""
        async with self._db.session_factory() as session:
            row = await session.get(UploadFileRecord, file_id)
            if row is None or row.session_id != session_id:
                return None
            return row
