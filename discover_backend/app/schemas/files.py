"""文件数据模型（跨边界 DTO，CLAUDE.md §3）。

包含接入层 API 请求/响应契约与文件注册表产物 DTO：
- ArtifactRecord：工具产物事件 / 预览路由的载体（持久化载体为 ORM upload_files，
  字节在存储层）。
- UploadConfig / FileResponse：文件 API 对外契约。

端点形态：
- GET  /files/upload            — 上传限制配置
- POST /files/upload            — 上传文件
- GET  /files/{file_id}/preview — 流式返回原始文件（inline 预览）
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    """时区感知的当前 UTC 时间（文件记录时间戳统一入口）。"""
    return datetime.now(UTC)


class ArtifactRecord(BaseModel):
    """产物记录（跨边界 DTO）。字节在存储层，元数据据此对外暴露。

    文件注册表多消费方共享、不强绑定会话/智能体（用户决策），故 DTO 不含
    session_id/agent_id。
    """

    artifact_id: str
    filename: str
    media_type: str
    size_bytes: int
    created_at: datetime = Field(default_factory=utc_now)


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
