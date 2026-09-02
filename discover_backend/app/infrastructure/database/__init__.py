"""持久化层：数据库引擎、ORM 基类与模型。

导入本包即注册全部 ORM 模型到 Base.metadata（供 Alembic 自动迁移）。
跨边界 DTO 仍用 pydantic，见 session/models.py。
"""

from app.infrastructure.database.base import Base, local_now
from app.infrastructure.database.engine import Database
from app.infrastructure.database.models import Account, DedupClue, UploadFileRecord

__all__ = ["Account", "Base", "Database", "DedupClue", "UploadFileRecord", "local_now"]
