"""持久化仓库层（Facade）：结构化状态读写统一收拢。

分层目录（用户决策 2026-08）：与 `app/services` 并列，仓库只负责
ORM 读写契约；业务编排在 services 层。
"""

from app.repositories.dedup import DedupStore

__all__ = ["DedupStore"]
