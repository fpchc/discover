"""存储层：文件存储后端抽象 + 本地实现（Blob Engine）。

字节流入存储层（LocalStorage/S3/OSS/COS），业务元数据入库。
上层只面向 BaseStorage 抽象，不依赖具体后端（DIP，CLAUDE.md §6）。
"""

from platform_engine.storage.base import BaseStorage
from platform_engine.storage.local import LocalStorage

__all__ = ["BaseStorage", "LocalStorage"]
