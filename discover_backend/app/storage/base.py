"""文件存储后端基础抽象 — BaseStorage ABC.

所有存储实现（LocalStorage, S3Storage, OSSStorage, COSStorage）必须实现此协议.

方案三：纯 Blob Engine 模式（极简 UUID 扁平化）
- 对象存储只负责存字节流，对象 Key 为 {uuid}.{ext} 纯 UUID 无目录层级
- 全部业务元数据（名称、类型、大小、创建时间、关联关系）100% 存数据库
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator


class BaseStorage(ABC):
    """文件存储后端基础抽象 — 本地/S3/OSS/COS 统一接口.

    设计原则:
    - 所有方法为 async — 存储 I/O 必须非阻塞（CLAUDE.md §4）.
    - filename 为存储内部 Key（UUID 扁平格式: {uuid}.{ext}，无目录层级）.
    - save / load_once / load_stream / download / exists / delete 为必须实现的核心方法.
    - scan 为可选方法，仅部分后端支持.
    """

    @abstractmethod
    async def save(self, filename: str, data: bytes) -> None:
        """保存文件.

        Args:
            filename: 存储 Key（UUID 扁平格式: {uuid}.{ext}）.
            data: 原始字节.
        """
        raise NotImplementedError

    @abstractmethod
    async def load_once(self, filename: str) -> bytes:
        """一次性读取文件全部内容.

        Args:
            filename: 存储 Key.

        Returns:
            文件完整内容.

        Raises:
            FileNotFoundError: filename 对应的文件不存在.
        """
        raise NotImplementedError

    @abstractmethod
    def load_stream(self, filename: str) -> AsyncGenerator[bytes, None]:
        """流式读取文件内容（异步生成器，非协程）.

        Args:
            filename: 存储 Key.

        Yields:
            文件内容块.

        Raises:
            FileNotFoundError: filename 对应的文件不存在.
        """
        raise NotImplementedError

    @abstractmethod
    async def download(self, filename: str, target_filepath: str) -> None:
        """下载文件到本地指定路径.

        Args:
            filename: 存储 Key.
            target_filepath: 本地目标文件路径.

        Raises:
            FileNotFoundError: filename 对应的文件不存在.
        """
        raise NotImplementedError

    @abstractmethod
    async def exists(self, filename: str) -> bool:
        """检查文件是否存在.

        Args:
            filename: 存储 Key.
        """
        raise NotImplementedError

    @abstractmethod
    async def delete(self, filename: str) -> None:
        """删除文件.

        Args:
            filename: 存储 Key.

        Raises:
            FileNotFoundError: filename 对应的文件不存在.
        """
        raise NotImplementedError

    @abstractmethod
    async def url(self, filename: str) -> str:
        """生成文件公开访问 URL.

        # pragma: 简化 — URL 生成依赖应用层 DB file_id，存储层只暴露内部 Key；
        # 下载路由由接入层按 record 生成，本方法存储后端通常不实现。
        """
        raise NotImplementedError

    async def scan(self, path: str, files: bool = True, directories: bool = False) -> list[str]:
        """扫描指定路径下的文件和目录.

        此方法仅在部分存储后端实现（如本地文件系统）.
        S3/OSS/COS 等对象存储默认不支持.

        方案三下 scan 几乎不需要 — 所有元数据查数据库即可.

        Args:
            path: 扫描路径（相对于存储根目录）.
            files: 是否包含文件.
            directories: 是否包含目录.

        Returns:
            匹配的文件/目录名列表.

        Raises:
            NotImplementedError: 当前存储后端不支持扫描.
        """
        raise NotImplementedError("This storage backend doesn't support scanning")
