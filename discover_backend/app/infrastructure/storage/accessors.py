"""存储扩展：按 storage_type 选择存储后端（BaseStorage 抽象）。

"local" → LocalStorage（本地磁盘，Blob Engine：UUID 扁平）；"s3" 为后续
扩展点，本次未实现，选择时抛 ConfigError。厂商后端经 BaseStorage 同一接口
接入，业务层无感知。
"""

from __future__ import annotations

from fastapi import FastAPI

from app.config.settings import Settings, active_settings
from app.infrastructure.storage.base import BaseStorage
from app.infrastructure.storage.local import LocalStorage
from app.infrastructure.storage.types import StorageType
from app.shared.errors.base import ConfigError

_storage: BaseStorage | None = None


def is_enabled() -> bool:
    """由配置开关控制。"""
    return active_settings().storage_enabled


def init_app(app: FastAPI | None) -> None:
    """按配置构建存储后端。"""
    global _storage
    settings = active_settings()
    _storage = _build_storage(StorageType(settings.storage_backend), settings)


def _build_storage(backend: StorageType, settings: Settings) -> BaseStorage:
    if backend is StorageType.LOCAL:
        return LocalStorage(settings.storage_root_dir)
    if backend is StorageType.S3:
        # 扩展点：S3 后端本次未实现
        raise ConfigError(f"存储后端未实现：{backend.value}")
    raise ConfigError(f"未知存储后端：{backend.value}")


async def startup(app: FastAPI) -> None:
    """本地存储无资源需开启。"""


async def shutdown(app: FastAPI) -> None:
    """本地存储无资源需释放。"""


def get_storage() -> BaseStorage:
    """取存储后端；扩展未启用时抛断言。"""
    assert _storage is not None
    return _storage
