"""文件存储后端抽象 — BaseStorage ABC（Blob Engine 模式）。

所有存储实现（LocalStorage / S3Storage / OSSStorage / COSStorage …）必须
实现此接口。设计原则：

- 所有方法 async — 存储 I/O 非阻塞（CLAUDE.md §4）。
- filename 为存储内部 Key（UUID 扁平格式 {uuid}.{ext}，无目录层级）。
- save / load_once / load_stream / download / exists / delete 为核心方法；
  url 依赖应用层 DB file_id，存储后端通常不实现；scan 仅部分后端支持。
- 字节流入存储层，业务元数据 100% 入库（DB）。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator


class BaseStorage(ABC):
    """文件存储后端统一接口（本地 / S3 / OSS / COS …）。"""

    @abstractmethod
    async def save(self, filename: str, data: bytes) -> None:
        """保存文件（存储 Key 为 UUID 扁平格式）。"""

    @abstractmethod
    async def load_once(self, filename: str) -> bytes:
        """一次性读取文件全部内容。

        Raises:
            FileNotFoundError: filename 对应的文件不存在.
        """

    @abstractmethod
    def load_stream(self, filename: str) -> AsyncGenerator[bytes, None]:
        """流式读取文件内容（异步生成器，非协程）。"""

    @abstractmethod
    async def download(self, filename: str, target_filepath: str) -> None:
        """下载文件到本地指定路径。"""

    @abstractmethod
    async def exists(self, filename: str) -> bool:
        """检查文件是否存在。"""

    @abstractmethod
    async def delete(self, filename: str) -> None:
        """删除文件。"""

    @abstractmethod
    async def url(self, filename: str) -> str:
        """生成文件公开访问 URL。

        # pragma: 简化 — URL 生成依赖应用层 DB file_id，存储层只暴露内部 Key；
        # 下载路由由接入层按 record 生成，本方法存储后端通常不实现。
        """

    async def scan(self, path: str, files: bool = True, directories: bool = False) -> list[str]:
        """扫描指定路径下的文件和目录（仅部分后端实现，如本地文件系统）。"""
        raise NotImplementedError("This storage backend doesn't support scanning")
