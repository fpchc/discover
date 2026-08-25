"""产物下载接口（L4，script-sandbox-spec §8）。

下载前校验会话归属，防产物标识泄漏后被枚举。响应头强制
Content-Disposition: attachment + X-Content-Type-Options: nosniff，
防 HTML 产物被浏览器当页面执行。字节从存储层流式回传。
"""

from urllib.parse import quote

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.container import AppServices, get_services
from app.errors.base import SessionNotFoundError

router = APIRouter(prefix="/sessions", tags=["artifacts"])


@router.get("/{session_id}/artifacts/{artifact_id}")
async def download_artifact(
    session_id: str,
    artifact_id: str,
    services: AppServices = Depends(get_services),
) -> StreamingResponse:
    """按会话归属下载产物；归属不符一律 404（不可枚举）。"""
    assert services.sessions is not None
    assert services.storage is not None
    download = await services.sessions.resolve_download(session_id, artifact_id)
    if download is None:
        raise SessionNotFoundError("产物不存在")
    headers = {
        "Content-Disposition": (f"attachment; filename*=UTF-8''{quote(download.record.filename)}"),
        "X-Content-Type-Options": "nosniff",
    }
    stream = services.storage.load_stream(download.storage_key)
    return StreamingResponse(
        stream,
        media_type=download.record.media_type,
        headers=headers,
    )
