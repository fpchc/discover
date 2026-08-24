"""持久化层：数据库引擎、ORM 基类与模型。

导入本包即注册全部 ORM 模型到 Base.metadata（供 Alembic 自动迁移）。
跨边界 DTO 仍用 pydantic，见 session/models.py。
"""

from platform_engine.db.base import Base, utc_now
from platform_engine.db.engine import Database
from platform_engine.db.models import DedupClue, UploadFileRecord

__all__ = ["Base", "Database", "DedupClue", "UploadFileRecord", "utc_now"]
