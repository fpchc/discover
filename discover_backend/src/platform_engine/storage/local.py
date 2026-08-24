"""本地文件系统存储后端（Blob Engine：UUID 扁平，无目录层级）。

文件落在 storage_root_dir/{uuid}.{ext}。所有文件 I/O 走 anyio 线程池，
避免阻塞事件循环（CLAUDE.md §4）。P1 本地存储；S3/OSS/COS 为后续扩展点，
通过 BaseStorage 同一接口切换。
"""

from __future__ import annotations

import shutil
from collections.abc import AsyncGenerator
from pathlib import Path

import anyio

from platform_engine.storage.base import BaseStorage

_CHUNK_SIZE = 64 * 1024


def _write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _copy_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)


def _scan_dir(target: Path, files: bool, directories: bool) -> list[str]:
    return sorted(
        entry.name
        for entry in target.iterdir()
        if (files and entry.is_file()) or (directories and entry.is_dir())
    )


class LocalStorage(BaseStorage):
    """本地磁盘存储：根目录扁平存字节流。"""

    def __init__(self, root: Path) -> None:
        self._root = root

    @staticmethod
    def _validate_key(filename: str) -> None:
        """存储键须为扁平文件名（{uuid}.{ext}），拒绝穿越与路径分隔符。"""
        path = Path(filename)
        if not filename or path.is_absolute() or path.name != filename or ".." in path.parts:
            raise ValueError(f"非法存储键：{filename!r}")

    def _resolve(self, filename: str) -> Path:
        self._validate_key(filename)
        return self._root / filename

    async def save(self, filename: str, data: bytes) -> None:
        path = self._resolve(filename)
        await anyio.to_thread.run_sync(_write_bytes, path, data)

    async def load_once(self, filename: str) -> bytes:
        path = self._resolve(filename)
        if not path.is_file():
            raise FileNotFoundError(filename)
        return await anyio.to_thread.run_sync(path.read_bytes)

    async def load_stream(self, filename: str) -> AsyncGenerator[bytes, None]:
        path = self._resolve(filename)
        if not path.is_file():
            raise FileNotFoundError(filename)
        with path.open("rb") as handle:
            while True:
                chunk = await anyio.to_thread.run_sync(handle.read, _CHUNK_SIZE)
                if not chunk:
                    break
                yield chunk

    async def download(self, filename: str, target_filepath: str) -> None:
        path = self._resolve(filename)
        if not path.is_file():
            raise FileNotFoundError(filename)
        await anyio.to_thread.run_sync(_copy_file, path, Path(target_filepath))

    async def exists(self, filename: str) -> bool:
        path = self._resolve(filename)
        return await anyio.to_thread.run_sync(path.is_file)

    async def delete(self, filename: str) -> None:
        path = self._resolve(filename)
        if not path.is_file():
            raise FileNotFoundError(filename)
        await anyio.to_thread.run_sync(path.unlink)

    async def url(self, filename: str) -> str:
        # pragma: 简化 — URL 生成属于应用层（需 DB file_id），本地无公开地址
        raise NotImplementedError("本地存储不提供公开 URL，下载路由由接入层生成")

    async def scan(self, path: str, files: bool = True, directories: bool = False) -> list[str]:
        target = self._root / path
        if not target.is_dir():
            return []
        return await anyio.to_thread.run_sync(_scan_dir, target, files, directories)
