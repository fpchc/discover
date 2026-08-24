"""Step 5 会话层测试。"""

from pathlib import Path

import pytest
import pytest_asyncio

from platform_engine.config.settings import Settings
from platform_engine.db.engine import Database
from platform_engine.errors.base import SessionError, SessionNotFoundError
from platform_engine.session.models import ArtifactRecord, SessionStatus
from platform_engine.session.service import SessionService, artifact_download_path
from platform_engine.storage.local import LocalStorage

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


async def test_bind_agent_updates_record(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)
    record = await service.create_session()
    updated = service.bind_agent(record.session_id, "finder")
    assert updated.agent_id == "finder"
    assert service.get_session(record.session_id).agent_id == "finder"


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


async def test_remove_session_keeps_agent_workspace(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)
    record = await service.create_session()
    ws = await service.workspace_for("finder")
    (ws.root / "note.txt").write_text("x", encoding="utf-8")
    await service.remove_session(record.session_id)
    assert ws.root.exists()  # 工作区按智能体共享，会话删除不影响
    with pytest.raises(SessionNotFoundError):
        service.get_session(record.session_id)


async def test_register_artifact_and_download_ownership(tmp_path: Path) -> None:
    service, storage = _service(tmp_path)
    owner = await service.create_session()
    other = await service.create_session()
    ws = await service.workspace_for("finder")
    src = ws.root / "报告.docx"
    src.write_bytes(b"hello")
    record = await service.register_artifact(
        session_id=owner.session_id,
        agent_id="finder",
        source_path=src,
        filename="报告.docx",
    )
    assert record.size_bytes == 5
    assert record.media_type.startswith("application/vnd")
    assert not src.exists()  # 源文件已清入存储层
    download = await service.resolve_download(owner.session_id, record.artifact_id)
    assert download is not None
    assert await storage.exists(download.storage_key)
    assert await storage.load_once(download.storage_key) == b"hello"
    # 归属不符 → 视为不存在（不可枚举）
    assert await service.resolve_download(other.session_id, record.artifact_id) is None


async def test_register_artifact_rejects_outside_workspace(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)
    record = await service.create_session()
    outside = tmp_path / "outside.txt"
    outside.write_text("x", encoding="utf-8")
    with pytest.raises(SessionError):
        await service.register_artifact(
            session_id=record.session_id,
            agent_id="finder",
            source_path=outside,
            filename="outside.txt",
        )


async def test_register_artifact_rejects_oversize(tmp_path: Path) -> None:
    service, _ = _service(tmp_path, artifact_max_size_bytes=10)
    record = await service.create_session()
    ws = await service.workspace_for("finder")
    src = ws.root / "big.txt"
    src.write_text("x" * 20, encoding="utf-8")
    with pytest.raises(SessionError):
        await service.register_artifact(
            session_id=record.session_id,
            agent_id="finder",
            source_path=src,
            filename="big.txt",
        )


@pytest.mark.parametrize(
    "bad",
    ["", ".", "..", "a/b", "a\\b", "a:b", "a<b", "a>b", 'a"b', "a|b", "a?b", "a*b", " x", "x "],
)
async def test_register_artifact_rejects_bad_filenames(tmp_path: Path, bad: str) -> None:
    service, _ = _service(tmp_path)
    record = await service.create_session()
    ws = await service.workspace_for("finder")
    src = ws.root / "src.bin"
    src.write_bytes(b"x")
    with pytest.raises(SessionError):
        await service.register_artifact(
            session_id=record.session_id,
            agent_id="finder",
            source_path=src,
            filename=bad,
        )


async def test_register_artifact_unknown_session(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)
    src = tmp_path / "x.txt"
    src.write_text("x", encoding="utf-8")
    with pytest.raises(SessionNotFoundError):
        await service.register_artifact(
            session_id="nope",
            agent_id="finder",
            source_path=src,
            filename="x.txt",
        )


async def test_remove_session_cleans_artifacts(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)
    record = await service.create_session()
    ws = await service.workspace_for("finder")
    src = ws.root / "f.txt"
    src.write_text("x", encoding="utf-8")
    artifact = await service.register_artifact(
        session_id=record.session_id,
        agent_id="finder",
        source_path=src,
        filename="f.txt",
    )
    await service.remove_session(record.session_id)
    assert await service.resolve_download(record.session_id, artifact.artifact_id) is None
    with pytest.raises(SessionNotFoundError):
        service.get_session(record.session_id)


def test_artifact_download_path() -> None:
    record = ArtifactRecord(
        artifact_id="abc123",
        session_id="sess",
        agent_id="finder",
        filename="f.txt",
        media_type="text/plain",
        size_bytes=1,
    )
    assert artifact_download_path(record) == "/sessions/sess/artifacts/abc123"
