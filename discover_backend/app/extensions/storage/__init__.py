"""存储后端子包：BaseStorage 抽象 + 后端实现（tt.png 结构）。

ext_storage 扩展按 storage_type 选择后端；业务层只依赖 BaseStorage 抽象。
"""

from app.extensions.storage.base_storage import BaseStorage
from app.extensions.storage.local_storage import LocalStorage
from app.extensions.storage.storage_type import StorageType

__all__ = ["BaseStorage", "LocalStorage", "StorageType"]
