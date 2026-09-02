"""文件服务测试——依赖本地 PostgreSQL（upload_files 元数据落库）。

覆盖工具产物登记（register）/ 用户上传（upload）/ 流式预览 / 文件名与大小校验。
"""

import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from app.config.settings import Settings
from app.domain.file.service import FileService, file_preview_path
from app.infrastructure.database.engine import Database
from app.infrastructure.storage.local import LocalStorage
from app.interfaces.schemas.files import ArtifactRecord
from app.shared.errors.base import SessionError

# 测试共享同一数据库引擎（连接池有界；产物场景才连接）。
_DATABASE = Database(Settings(_env_file=None))
_ACCOUNT_ID = str(uuid.uuid4())


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _dispose_database() -> None:
    yield
    await _DATABASE.dispose()


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    return Settings(
        _env_file=None,
        agent_workspace_root_dir=tmp_path,
        storage_root_dir=tmp_path / "storage",
        **overrides,
    )


def _service(tmp_path: Path, **overrides: object) -> tuple[FileService, LocalStorage]:
    settings = _settings(tmp_path, **overrides)
    storage = LocalStorage(settings.storage_root_dir)
    return FileService(settings, _DATABASE, storage), storage


async def test_register_artifact_and_preview(tmp_path: Path) -> None:
    service, storage = _service(tmp_path)
    src = tmp_path / "报告.docx"
    src.write_bytes(b"hello")
    record = await service.register(created_by=_ACCOUNT_ID, source_path=src, filename="报告.docx")
    assert record.size_bytes == 5
    assert record.media_type.startswith("application/vnd")
    assert not src.exists()  # 源文件已清入存储层
    row = await service.get(record.artifact_id)
    assert row is not None
    assert await storage.exists(row.storage_key)
    assert await storage.load_once(row.storage_key) == b"hello"
    stream, mime, name = await service.get_content_stream_by_id(record.artifact_id)
    assert mime.startswith("application/vnd")
    assert name == "报告.docx"
    assert b"".join([chunk async for chunk in stream]) == b"hello"


async def test_register_artifact_rejects_non_regular_source(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)
    directory = tmp_path / "adir"
    directory.mkdir()
    with pytest.raises(SessionError):
        await service.register(created_by=_ACCOUNT_ID, source_path=directory, filename="x.txt")


async def test_register_artifact_rejects_oversize(tmp_path: Path) -> None:
    service, _ = _service(tmp_path, artifact_max_size_bytes=10)
    src = tmp_path / "big.txt"
    src.write_text("x" * 20, encoding="utf-8")
    with pytest.raises(SessionError):
        await service.register(created_by=_ACCOUNT_ID, source_path=src, filename="big.txt")


@pytest.mark.parametrize(
    "bad",
    ["", ".", "..", "a/b", "a\\b", "a:b", "a<b", "a>b", 'a"b', "a|b", "a?b", "a*b", " x", "x "],
)
async def test_register_artifact_rejects_bad_filenames(tmp_path: Path, bad: str) -> None:
    service, _ = _service(tmp_path)
    src = tmp_path / "src.bin"
    src.write_bytes(b"x")
    with pytest.raises(SessionError):
        await service.register(created_by=_ACCOUNT_ID, source_path=src, filename=bad)


def test_file_preview_path() -> None:
    record = ArtifactRecord(
        artifact_id="abc123",
        filename="f.txt",
        media_type="text/plain",
        size_bytes=1,
    )
    assert file_preview_path(record) == "/files/abc123/preview"


async def test_upload_file_creates_record(tmp_path: Path) -> None:
    service, storage = _service(tmp_path)
    resp = await service.upload(
        created_by=_ACCOUNT_ID, filename="pic.png", content=b"\x89PNG", mimetype="image/png"
    )
    assert resp.file_id
    assert resp.name == "pic.png"
    assert resp.size_bytes == 4
    row = await service.get(resp.file_id)
    assert row is not None and row.used is False  # 上传未消费，used=false
    assert await storage.load_once(row.storage_key) == b"\x89PNG"


async def test_upload_rejects_disallowed_extension(tmp_path: Path) -> None:
    service, _ = _service(tmp_path, storage_upload_allowed_extensions="png,jpg")
    with pytest.raises(SessionError):
        await service.upload(
            created_by=_ACCOUNT_ID,
            filename="evil.exe",
            content=b"MZ",
            mimetype="application/octet-stream",
        )


async def test_upload_rejects_oversize(tmp_path: Path) -> None:
    service, _ = _service(tmp_path, storage_upload_file_size_limit_mb=0)
    with pytest.raises(SessionError):
        await service.upload(
            created_by=_ACCOUNT_ID, filename="a.txt", content=b"x", mimetype="text/plain"
        )
