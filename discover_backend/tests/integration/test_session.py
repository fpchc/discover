"""Step 5 会话层测试。"""

from pathlib import Path

import pytest
import pytest_asyncio
from app.catalog.models import AssistantTarget, TargetType
from app.config.settings import Settings
from app.db.engine import Database
from app.errors.base import SessionError, SessionNotFoundError
from app.extensions.storage.local_storage import LocalStorage
from app.session.models import ArtifactRecord, SessionStatus
from app.session.service import SessionService, file_preview_path

# 测试共享同一数据库引擎（连接池有界；假脚本场景不触 DB，产物场景才连接）。
_DATABASE = Database(Settings(_env_file=None))


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


def _service(tmp_path: Path, **overrides: object) -> tuple[SessionService, LocalStorage]:
    settings = _settings(tmp_path, **overrides)
    storage = LocalStorage(settings.storage_root_dir)
    return SessionService(settings, _DATABASE, storage), storage


async def test_create_session_creates_record(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)
    record = await service.create_session()
    assert record.session_id
    assert record.status == SessionStatus.ACTIVE


async def test_get_unknown_session_raises(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)
    with pytest.raises(SessionNotFoundError):
        service.get_session("nope")


async def test_bind_assistant_updates_record(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)
    record = await service.create_session()
    target = AssistantTarget(type=TargetType.EXPERT, id="finder")
    updated = service.bind_assistant(record.session_id, target)
    assert updated.assistant_target == target
    assert service.get_session(record.session_id).assistant_target == target


async def test_delete_session_removes_record(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)
    record = await service.create_session()
    assert service.delete_session(record.session_id) is True
    with pytest.raises(SessionNotFoundError):
        service.get_session(record.session_id)


async def test_delete_session_missing_returns_false(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)
    assert service.delete_session("nope") is False


async def test_workspace_agent_keyed_shared_across_sessions(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)
    await service.create_session()
    await service.create_session()
    ws1 = await service.workspace_for("finder")
    ws2 = await service.workspace_for("finder")
    assert ws1.root == ws2.root  # 同一智能体跨会话共享工作区
    assert ws1.root.is_relative_to(tmp_path)
    ws_other = await service.workspace_for("analyst")
    assert ws_other.root != ws1.root  # 不同智能体隔离


@pytest.mark.parametrize(
    "bad_id",
    ["../evil", "..", ".", "evil/../../", "Evil", "evil-", "-evil", "evil/x", ""],
)
async def test_workspace_rejects_traversal_ids(tmp_path: Path, bad_id: str) -> None:
    service, _ = _service(tmp_path)
    with pytest.raises(SessionError):
        await service.workspace_for(bad_id)


async def test_register_artifact_and_preview(tmp_path: Path) -> None:
    service, storage = _service(tmp_path)
    ws = await service.workspace_for("finder")
    src = ws.root / "报告.docx"
    src.write_bytes(b"hello")
    record = await service.register_artifact(source_path=src, filename="报告.docx")
    assert record.size_bytes == 5
    assert record.media_type.startswith("application/vnd")
    assert not src.exists()  # 源文件已清入存储层
    row = await service._files.get(record.artifact_id)
    assert row is not None
    assert await storage.exists(row.storage_key)
    assert await storage.load_once(row.storage_key) == b"hello"
    stream, mime, name = await service.resolve_preview(record.artifact_id)
    assert mime.startswith("application/vnd")
    assert name == "报告.docx"
    assert b"".join([chunk async for chunk in stream]) == b"hello"


async def test_register_artifact_rejects_non_regular_source(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)
    directory = tmp_path / "adir"
    directory.mkdir()
    with pytest.raises(SessionError):
        await service.register_artifact(source_path=directory, filename="x.txt")


async def test_register_artifact_rejects_oversize(tmp_path: Path) -> None:
    service, _ = _service(tmp_path, artifact_max_size_bytes=10)
    ws = await service.workspace_for("finder")
    src = ws.root / "big.txt"
    src.write_text("x" * 20, encoding="utf-8")
    with pytest.raises(SessionError):
        await service.register_artifact(source_path=src, filename="big.txt")


@pytest.mark.parametrize(
    "bad",
    ["", ".", "..", "a/b", "a\\b", "a:b", "a<b", "a>b", 'a"b', "a|b", "a?b", "a*b", " x", "x "],
)
async def test_register_artifact_rejects_bad_filenames(tmp_path: Path, bad: str) -> None:
    service, _ = _service(tmp_path)
    ws = await service.workspace_for("finder")
    src = ws.root / "src.bin"
    src.write_bytes(b"x")
    with pytest.raises(SessionError):
        await service.register_artifact(source_path=src, filename=bad)


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
    resp = await service.upload_file(filename="pic.png", content=b"\x89PNG", mimetype="image/png")
    assert resp.file_id
    assert resp.name == "pic.png"
    assert resp.size_bytes == 4
    row = await service._files.get(resp.file_id)
    assert row is not None and row.used is False  # 上传未消费，used=false
    assert await storage.load_once(row.storage_key) == b"\x89PNG"


async def test_upload_rejects_disallowed_extension(tmp_path: Path) -> None:
    service, _ = _service(tmp_path, storage_upload_allowed_extensions="png,jpg")
    with pytest.raises(SessionError):
        await service.upload_file(
            filename="evil.exe", content=b"MZ", mimetype="application/octet-stream"
        )


async def test_upload_rejects_oversize(tmp_path: Path) -> None:
    service, _ = _service(tmp_path, storage_upload_file_size_limit_mb=0)
    with pytest.raises(SessionError):
        await service.upload_file(filename="a.txt", content=b"x", mimetype="text/plain")
