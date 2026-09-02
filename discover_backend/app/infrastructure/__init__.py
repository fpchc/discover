"""基础设施：外部技术实现——数据库 / 存储后端 / 日志内核。

port 抽象（如 BaseStorage）与 adapter（Local/S3）同包放置；
能力层与领域层只依赖抽象，具体实现由 bootstrap 组装。
"""

from app.infrastructure.database import Account, Base, Database, DedupClue, UploadFileRecord

__all__ = [
    "Account",
    "Base",
    "Database",
    "DedupClue",
    "UploadFileRecord",
]
