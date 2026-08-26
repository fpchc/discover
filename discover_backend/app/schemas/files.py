"""文件 API 请求 / 响应模型（接入层对外契约，跨边界一律 pydantic）。

端点形态：
- GET  /files/upload            — 上传限制配置
- POST /files/upload            — 上传文件
- GET  /files/{file_id}/preview — 流式返回原始文件（inline 预览）
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class UploadConfig(BaseModel):
    """上传限制配置（供前端约束输入）。"""

    file_size_limit: int
    file_type_limit: list[str]


class FileResponse(BaseModel):
    """上传/文件记录响应。"""

    file_id: str
    name: str
    media_type: str
    size_bytes: int
    created_at: datetime
