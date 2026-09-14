"""技能包管理跨边界 DTO（管理员在线修改/调试）。

持久化载体为 ORM `agent_packages` / `agent_package_entries`，字节 bundle 在存储层；
本文件只承载对外请求/响应契约与服务返回模型。
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class PackageStatus(StrEnum):
    """技能包生命周期状态。"""

    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class PackageFile(BaseModel):
    """单个可编辑文件（AGENT/SKILL 正文、references、templates）。"""

    path: str
    content: str


class PackageSummary(BaseModel):
    """技能包列表项。"""

    package_id: str
    agent_id: str
    version: str
    status: PackageStatus
    enabled: bool
    updated_at: datetime


class PackageDetail(BaseModel):
    """技能包详情：元数据 + 可编辑文件全集。"""

    package_id: str
    agent_id: str
    version: str
    status: PackageStatus
    enabled: bool
    files: list[PackageFile] = Field(default_factory=list)
    published_at: datetime | None = None
    updated_at: datetime


class CreateDraftRequest(BaseModel):
    """创建草稿请求。"""

    version: str
    template_id: str = "standard"
    display_name: str | None = None


class SaveFileRequest(BaseModel):
    """保存单个可编辑文件请求。"""

    path: str
    content: str


class ValidateResult(BaseModel):
    """静态校验结果。"""

    ok: bool
    errors: list[str] = Field(default_factory=list)


class PublishRequest(BaseModel):
    """发布请求（版本取自草稿，保留空体兼容未来扩展）。"""


class RollbackRequest(BaseModel):
    """回滚请求。"""

    version: str


class PublishedPackage(BaseModel):
    """已发布版本（服务内部与发布/回滚响应共用）。"""

    agent_id: str
    version: str
    storage_key: str
    checksum: str


class DebugPreviewRequest(BaseModel):
    """草稿预览对话请求。"""

    user_input: str


class ToolSmokeRequest(BaseModel):
    """工具冒烟测试请求。"""

    tool_name: str
    arguments: dict[str, object] = Field(default_factory=dict)


class DebugRunEvent(BaseModel):
    """调试 run 的单个事件（RunEvent 序列化投影）。"""

    seq: int
    event_type: str
    payload: dict[str, object]


class PreviewResult(BaseModel):
    """草稿预览对话结果。"""

    answer: str
    outcome_type: str | None = None
    thinking: str = ""
    events: list[DebugRunEvent] = Field(default_factory=list)


class ToolSmokeResult(BaseModel):
    """工具冒烟测试结果。"""

    call_id: str
    tool_name: str
    ok: bool
    content: str = ""
    error_category: str | None = None
    message: str = ""
    suggestion: str | None = None
    duration_ms: int = 0
    truncated: bool = False
    produced_files: list[str] = Field(default_factory=list)


__all__ = [
    "CreateDraftRequest",
    "DebugPreviewRequest",
    "DebugRunEvent",
    "PackageDetail",
    "PackageFile",
    "PackageStatus",
    "PackageSummary",
    "PreviewResult",
    "PublishRequest",
    "PublishedPackage",
    "RollbackRequest",
    "SaveFileRequest",
    "ToolSmokeRequest",
    "ToolSmokeResult",
    "ValidateResult",
]
