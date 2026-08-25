"""持久化层：数据库引擎、ORM 基类与模型。

导入本包即注册全部 ORM 模型到 Base.metadata（供 Alembic 自动迁移）。
跨边界 DTO 仍用 pydantic，见 session/models.py。
"""

from app.db.base import Base, utc_now
from app.db.engine import Database
from app.db.models import DedupClue, UploadFileRecord

__all__ = ["Base", "Database", "DedupClue", "UploadFileRecord", "utc_now"]
