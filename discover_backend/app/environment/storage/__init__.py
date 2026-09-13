"""存储后端子包：BaseStorage 抽象 + 后端实现（tt.png 结构）。

ext_storage 扩展按 storage_type 选择后端；业务层只依赖 BaseStorage 抽象。
"""

from app.environment.storage.base import BaseStorage
from app.environment.storage.local import LocalStorage
from app.environment.storage.types import StorageType

__all__ = ["BaseStorage", "LocalStorage", "StorageType"]
