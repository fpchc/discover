"""HTTP 文件 API 测试——依赖本地 PostgreSQL（文件元数据入库 upload_files 表）。

GET  /files/upload 上传配置；POST /files/upload 上传；GET /files/{id}/preview 预览。
"""

import httpx
from app.schemas.files import FileResponse, UploadConfig


async def test_upload_config(api_ctx: tuple[object, httpx.AsyncClient]) -> None:
    _app, client = api_ctx
    response = await client.get("/api/v1/files/upload")
    assert response.status_code == 200
    config = UploadConfig.model_validate(response.json())
    assert config.file_size_limit > 0
    assert config.file_type_limit


async def test_upload_then_preview(api_ctx: tuple[object, httpx.AsyncClient]) -> None:
    app, client = api_ctx
    response = await client.post(
        "/api/v1/files/upload",
        files={"file": ("报告.md", "# 报告".encode(), "text/markdown")},
    )
    assert response.status_code == 200
    payload = FileResponse.model_validate(response.json())
    assert payload.name == "报告.md"
    assert payload.size_bytes == len("# 报告".encode())

    preview = await client.get(f"/api/v1/files/{payload.file_id}/preview")
    assert preview.status_code == 200
    assert preview.content == "# 报告".encode()
    assert "inline" in preview.headers["content-disposition"]
    # 预览即标记 used（供后续清理）
    row = await app.state.services.sessions._files.get(payload.file_id)
    assert row is not None and row.used


async def test_upload_rejects_disallowed_extension(
    api_ctx: tuple[object, httpx.AsyncClient],
) -> None:
    _app, client = api_ctx
    response = await client.post(
        "/api/v1/files/upload",
        files={"file": ("evil.exe", b"MZ", "application/octet-stream")},
    )
    assert response.status_code == 400


async def test_preview_unknown_404(api_ctx: tuple[object, httpx.AsyncClient]) -> None:
    _app, client = api_ctx
    response = await client.get("/api/v1/files/nonexistent/preview")
    assert response.status_code == 404
