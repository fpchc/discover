"""storage 插件：按 storage_backend 选择存储后端（BaseStorage 抽象）。

"local" → LocalStorage（本地磁盘，Blob Engine：UUID 扁平）；"s3" 为后续
扩展点，本次未实现，选择时抛 ConfigError。S3/OSS/COS 后端经 BaseStorage
同一接口接入，业务层无感知。
"""

from __future__ import annotations

from app.config.settings import Settings
from app.errors.base import ConfigError
from app.plugins.base import Plugin, register
from app.storage.base import BaseStorage
from app.storage.local import LocalStorage


@register
class StoragePlugin(Plugin):
    """文件存储后端选择器。"""

    name = "storage"

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self._storage: BaseStorage = self._build_storage(settings)

    @classmethod
    def is_enabled(cls, settings: Settings) -> bool:
        return settings.storage_enabled

    @staticmethod
    def _build_storage(settings: Settings) -> BaseStorage:
        if settings.storage_backend == "local":
            return LocalStorage(settings.storage_root_dir)
        # "s3" 分支：扩展点，本次未实现
        raise ConfigError(f"存储后端未实现：{settings.storage_backend}")

    @property
    def client(self) -> BaseStorage:
        return self._storage

    async def startup(self) -> None:
        """本地存储无资源需开启。"""

    async def shutdown(self) -> None:
        """本地存储无资源需释放。"""
