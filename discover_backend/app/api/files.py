"""文件路由 — 上传与流式预览（L4，controller）。

方案：纯 Blob Engine 模式（极简 UUID 扁平化）
- 存储 Key: {uuid}.{ext}，无目录层级
- 外部访问统一走 DB record ID（/files/{file_id}/preview）

端点:
  GET  /files/upload              — 获取上传限制配置
  POST /files/upload              — 上传文件
  GET  /files/{file_id}/preview   — 流式返回原始文件

职责边界: 只做参数提取 + 转调 FileService，不含业务逻辑。
"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, UploadFile
from fastapi.responses import StreamingResponse

from app.api.deps import get_current_account_id
from app.container import AppServices, get_services
from app.errors.base import BadRequestError
from app.schemas.files import FileResponse, UploadConfig

router = APIRouter(prefix="/files", tags=["storage"])


@router.get("/upload")
async def upload_config(services: AppServices = Depends(get_services)) -> UploadConfig:
    """获取上传限制配置（供前端约束输入）。"""
    settings = services.settings
    limit_mb = settings.storage_upload_file_size_limit_mb
    return UploadConfig(
        file_size_limit=limit_mb * 1024 * 1024,
        file_type_limit=[
            e.strip() for e in settings.storage_upload_allowed_extensions.split(",") if e.strip()
        ],
    )


@router.post("/upload")
async def upload_file(
    file: UploadFile,
    account_id: str = Depends(get_current_account_id),
    services: AppServices = Depends(get_services),
) -> FileResponse:
    """上传文件（归属当前账号）— 存储 Key 为 {uuid}.{ext}（极简 UUID 扁平化）。"""
    assert services.files is not None
    limit = services.settings.storage_upload_file_size_limit_mb * 1024 * 1024
    content = await file.read(limit + 1)
    if len(content) > limit:
        raise BadRequestError(f"文件超过大小上限（{limit} 字节）")
    return await services.files.upload(
        created_by=account_id,
        filename=file.filename or "unnamed",
        content=content,
        mimetype=file.content_type or "",
    )


@router.get("/{file_id}/preview")
async def preview_file(
    file_id: str,
    services: AppServices = Depends(get_services),
) -> StreamingResponse:
    """按 DB record id 流式返回原始文件（inline 预览）。"""
    assert services.files is not None
    stream, media_type, name = await services.files.get_content_stream_by_id(file_id)
    encoded_name = quote(name, safe="")
    return StreamingResponse(
        stream,
        media_type=media_type or "application/octet-stream",
        headers={
            "Content-Disposition": f"inline; filename*=UTF-8''{encoded_name}",
        },
    )
