"""S3 兼容对象存储后端（扩展点：本次未实现）。

结构占位：后续实现时经 httpx 手写 AWS SigV4 签名（或引入 SDK 需 pragma
豁免 CLAUDE.md §1「外部 HTTP 唯一出口为 httpx」），实现 BaseStorage 全部
抽象方法即可接入。当前由 ext_storage 对 S3 类型直接抛 ConfigError，
本类不会被实例化。
"""

from __future__ import annotations

from app.infrastructure.storage.base import BaseStorage


class S3Storage(BaseStorage):
    """S3 后端占位：抽象类，未实现任何方法。"""
