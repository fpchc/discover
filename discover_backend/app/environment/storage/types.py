"""存储后端类型枚举。

配置项 storage_backend 与枚举值一一对应。当前仅 LOCAL 已实现；S3 为
扩展点占位（aws_s3_storage.py）。其余厂商后端（OSS / COS / Azure Blob …）
后续按同一枚举与 BaseStorage 接口接入。
"""

from __future__ import annotations

from enum import StrEnum


class StorageType(StrEnum):
    """存储后端类型。"""

    LOCAL = "local"
    S3 = "s3"
