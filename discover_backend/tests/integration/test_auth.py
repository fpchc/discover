"""账号认证集成测试——依赖本地 PostgreSQL。

覆盖：AuthService 登录/账号/用量/资料（昵称、头像、密码）、dedup_clues 按账号
隔离（组合键）、HTTP /auth/login 与 /users/me/* 端点。迁移须已应用
（alembic upgrade head）。
"""

from __future__ import annotations

import tempfile
import uuid
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest
import pytest_asyncio
from app.config.settings import Settings
from app.db.engine import Database
from app.db.models import Account, Message, UploadFileRecord
from app.errors.base import BadRequestError, UnauthorizedError
from app.extensions.storage.local_storage import LocalStorage
from app.repositories.dedup import DedupStore
from app.schemas.auth import AvatarConfig, LoginResponse
from app.schemas.conversations import TurnRecord, TurnUsage
from app.services.auth import AuthService
from app.services.auth_security import JwtService, PasswordHasher
from app.services.conversations import ConversationService
from app.services.elecnest_sso import ElecnestSSOClient
from app.services.files import FileService
from sqlalchemy import select

_DATABASE = Database(Settings(_env_file=None))
_SECRET = "test-secret-0123456789abcdef0123456789abcdef"
# 最小合法 PNG（文件头 magic 足够通过内容校验）
_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _dispose_database() -> None:
    yield
    await _DATABASE.dispose()


def _settings(*, elecnest_enabled: bool = False) -> Settings:
    return Settings(
        _env_file=None,
        jwt_secret_key=_SECRET,
        elecnest_sso_enabled=elecnest_enabled,
    )


def _service(
    storage_root: Path | None = None,
    *,
    elecnest: ElecnestSSOClient | None = None,
    elecnest_enabled: bool = False,
) -> AuthService:
    """AuthService（注入 FileService；storage_root 缺省用系统临时目录）。"""
    root = storage_root if storage_root is not None else Path(tempfile.mkdtemp(prefix="auth-test-"))
    settings = _settings(elecnest_enabled=elecnest_enabled)
    files = FileService(settings, _DATABASE, LocalStorage(root))
    return AuthService(
        settings,
        _DATABASE,
        ConversationService(_DATABASE),
        files,
        elecnest=elecnest,
    )


def _mock_elecnest(data: dict[str, object] | None) -> ElecnestSSOClient:
    """统一登录客户端（MockTransport 拦截外部请求，CLAUDE.md §12：禁真实网络）。"""

    def _handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/api/login/getUserInfo")
        assert request.url.params["token"] == "sso-token"
        return httpx.Response(200, json={"data": data})

    transport = httpx.MockTransport(_handler)
    http = httpx.AsyncClient(transport=transport)
    return ElecnestSSOClient(_settings(), http)


def _token_for(account_id: str) -> dict[str, str]:
    """为该账号构造 Authorization 头（HTTP 端点测试用）。"""
    token = JwtService(_settings()).encode(account_id)
    return {"Authorization": f"Bearer {token}"}


async def _create_account(
    phone: str,
    password: str,
    *,
    is_system: bool = False,
    status: str = "active",
    name: str | None = None,
) -> str:
    """建真实账号（Argon2id 哈希入库），返回 account_id（uuid 文本）。"""
    hasher = PasswordHasher(_settings())
    account = Account(
        id=uuid.uuid4(),
        name=name or f"用户{phone}",
        phone=phone,
        username=phone,
        password_hash=hasher.hash(password),
        is_system=is_system,
        status=status,
    )
    async with _DATABASE.session_factory() as session:
        session.add(account)
        await session.commit()
    return str(account.id)


def _wall(day: date, hour: int = 10) -> datetime:
    """GMT+8 墙钟时间（naive，与 local_now() 落库口径一致）。"""
    return datetime.combine(day, time(hour))


async def _insert_message(
    account_id: str,
    *,
    day: date,
    conversation_id: str,
    prompt: int = 0,
    completion: int = 0,
    total: int = 0,
    cached_read: int = 0,
    cached_write: int = 0,
) -> None:
    """直接落库一条指定日期的消息（构造逐日聚合测试数据）。"""
    async with _DATABASE.session_factory() as session:
        session.add(
            Message(
                message_id=uuid.uuid4().hex,
                conversation_id=conversation_id,
                created_by=account_id,
                query="q",
                prompt_tokens=prompt,
                completion_tokens=completion,
                total_tokens=total,
                cached_read_tokens=cached_read,
                cached_write_tokens=cached_write,
                created_at=_wall(day),
            )
        )
        await session.commit()


# ---- 登录 ----


async def test_login_success_returns_token() -> None:
    phone = f"138{str(uuid.uuid4().int)[:8]}"
    account_id = await _create_account(phone, "pw-123")
    svc = _service()
    resp = await svc.login(phone, "pw-123")
    assert isinstance(resp, LoginResponse)
    assert resp.account_id == account_id
    assert resp.name is not None
    # token 解签即 account_id
    assert svc.decode_token(resp.token) == account_id


async def test_login_wrong_password_rejected() -> None:
    phone = f"139{str(uuid.uuid4().int)[:8]}"
    await _create_account(phone, "right")
    with pytest.raises(UnauthorizedError):
        await _service().login(phone, "wrong")


async def test_login_unknown_phone_rejected() -> None:
    with pytest.raises(UnauthorizedError):
        await _service().login("15000000000", "whatever")


async def test_login_disabled_account_rejected() -> None:
    phone = f"137{str(uuid.uuid4().int)[:8]}"
    await _create_account(phone, "pw", status="disabled")
    with pytest.raises(UnauthorizedError):
        await _service().login(phone, "pw")


# ---- 公司统一登录（elecnest SSO） ----


async def test_login_elecnest_creates_and_reuses_account() -> None:
    uid = 88001
    client = _mock_elecnest(
        {
            "uid": uid,
            "username": "zhangsan",
            "nickname": "张三",
            "phone": "13800000001",
            "avatar": "https://cdn.example.com/a.png",
        }
    )
    svc = _service(elecnest=client, elecnest_enabled=True)
    first = await svc.login_with_elecnest("sso-token", uid)
    assert isinstance(first, LoginResponse)
    assert first.account_id
    assert first.name == "张三"
    # 账号已按 elecnest_uid 落库并标 user_type=elecnest
    async with _DATABASE.session_factory() as session:
        row = await session.scalar(select(Account).where(Account.elecnest_uid == str(uid)))
        assert row is not None
        assert row.user_type == "elecnest"
        assert row.phone == "13800000001"
    # 二次登录复用同一账号（幂等）
    second = await svc.login_with_elecnest("sso-token", uid)
    assert second.account_id == first.account_id


async def test_login_elecnest_nickname_falls_back_to_username() -> None:
    uid = 88002
    client = _mock_elecnest({"uid": uid, "username": "lisi", "nickname": ""})
    resp = await _service(elecnest=client, elecnest_enabled=True).login_with_elecnest(
        "sso-token", uid
    )
    assert resp.name == "lisi"


async def test_login_elecnest_null_data_rejected() -> None:
    client = _mock_elecnest(None)
    with pytest.raises(UnauthorizedError):
        await _service(elecnest=client, elecnest_enabled=True).login_with_elecnest(
            "sso-token", 88003
        )


async def test_login_elecnest_disabled_rejected() -> None:
    client = _mock_elecnest({"uid": 88004, "username": "x", "nickname": "X"})
    with pytest.raises(BadRequestError):
        # 开关关闭：即使外部校验成功也拒绝
        await _service(elecnest=client, elecnest_enabled=False).login_with_elecnest(
            "sso-token", 88004
        )


# ---- 账号与用量 ----


async def test_get_account_record_excludes_password() -> None:
    phone = f"136{str(uuid.uuid4().int)[:8]}"
    account_id = await _create_account(phone, "pw", name="张三")
    record = await _service().get_account(account_id)
    assert record is not None
    assert record.account_id == account_id
    assert record.name == "张三"
    assert record.phone == phone
    assert not hasattr(record, "password_hash")  # 密码哈希永不外泄
    assert record.is_system is False


async def test_get_account_unknown_returns_none() -> None:
    assert await _service().get_account(str(uuid.uuid4())) is None


async def test_get_user_usage_aggregates_messages() -> None:
    account_id = str(uuid.uuid4())
    history = ConversationService(_DATABASE)
    for _ in range(3):
        await history.record_turn(
            uuid.uuid4().hex,
            TurnRecord(
                message_id=uuid.uuid4().hex,
                query="q",
                usage=TurnUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
                account_id=account_id,
            ),
        )
    usage = await _service().get_user_usage(account_id)
    assert usage is not None
    assert usage.message_count == 3
    assert usage.total_tokens == 45
    assert usage.prompt_tokens == 30
    assert usage.completion_tokens == 15


async def test_list_users_with_usage_covers_all_accounts() -> None:
    phone_a = f"135{str(uuid.uuid4().int)[:8]}"
    await _create_account(phone_a, "pw")
    phone_b = f"134{str(uuid.uuid4().int)[:8]}"
    await _create_account(phone_b, "pw", is_system=True)
    rows = await _service().list_users_with_usage()
    by_phone = {r.phone for r in rows}
    assert phone_a in by_phone
    assert phone_b in by_phone
    # 每个账号都有用量条目（无消息则为 0）
    assert all(isinstance(r.message_count, int) for r in rows)


# ---- 资料维护（昵称 / 头像 / 密码） ----


async def test_avatar_config_matches_settings() -> None:
    config = await _service().avatar_config()
    settings = _settings()
    assert isinstance(config, AvatarConfig)
    assert config.max_size_bytes == settings.avatar_max_size_bytes
    assert "png" in config.allowed_extensions
    assert config.max_dimension == settings.avatar_max_dimension
    assert config.min_dimension == settings.avatar_min_dimension


async def test_update_account_name() -> None:
    phone = f"132{str(uuid.uuid4().int)[:8]}"
    account_id = await _create_account(phone, "pw", name="旧名")
    record = await _service().update_account(account_id, name="  新昵称  ")
    assert record.name == "新昵称"
    async with _DATABASE.session_factory() as session:
        row = await session.get(Account, uuid.UUID(account_id))
        assert row is not None and row.name == "新昵称"


async def test_update_account_blank_name_rejected() -> None:
    phone = f"131{str(uuid.uuid4().int)[:8]}"
    account_id = await _create_account(phone, "pw")
    with pytest.raises(BadRequestError):
        await _service().update_account(account_id, name="   ")


async def test_update_account_unknown_raises() -> None:
    with pytest.raises(UnauthorizedError):
        await _service().update_account(str(uuid.uuid4()), name="x")


async def test_change_avatar_sets_preview_path(tmp_path: Path) -> None:
    phone = f"130{str(uuid.uuid4().int)[:8]}"
    account_id = await _create_account(phone, "pw")
    record = await _service(tmp_path).change_avatar(
        account_id, filename="avatar.png", content=_PNG_BYTES, mimetype="image/png"
    )
    assert record.avatar is not None and record.avatar.startswith("/files/")
    assert record.avatar.endswith("/preview")
    file_id = record.avatar.removeprefix("/files/").removesuffix("/preview")
    async with _DATABASE.session_factory() as session:
        row = await session.get(Account, uuid.UUID(account_id))
        assert row is not None and row.avatar == record.avatar
    # 文件元数据已落库（字节落盘由 FileService 保证）
    async with _DATABASE.session_factory() as session:
        file_row = await session.scalar(
            select(UploadFileRecord).where(UploadFileRecord.file_id == file_id)
        )
        assert file_row is not None and file_row.created_by == account_id


async def test_change_avatar_rejects_non_image_extension(tmp_path: Path) -> None:
    phone = f"129{str(uuid.uuid4().int)[:8]}"
    account_id = await _create_account(phone, "pw")
    with pytest.raises(BadRequestError):
        await _service(tmp_path).change_avatar(
            account_id, filename="evil.exe", content=b"MZ", mimetype="application/octet-stream"
        )


async def test_change_avatar_rejects_fake_image_content(tmp_path: Path) -> None:
    phone = f"128{str(uuid.uuid4().int)[:8]}"
    account_id = await _create_account(phone, "pw")
    with pytest.raises(BadRequestError):
        await _service(tmp_path).change_avatar(
            account_id, filename="fake.png", content=b"not really a png", mimetype="image/png"
        )


async def test_change_avatar_rejects_oversize(tmp_path: Path) -> None:
    phone = f"127{str(uuid.uuid4().int)[:8]}"
    account_id = await _create_account(phone, "pw")
    settings = Settings(_env_file=None, jwt_secret_key=_SECRET, avatar_max_size_bytes=4)
    files = FileService(settings, _DATABASE, LocalStorage(tmp_path))
    svc = AuthService(settings, _DATABASE, ConversationService(_DATABASE), files)
    with pytest.raises(BadRequestError):
        await svc.change_avatar(
            account_id, filename="big.png", content=_PNG_BYTES, mimetype="image/png"
        )


async def test_change_password_success_then_old_password_fails() -> None:
    phone = f"126{str(uuid.uuid4().int)[:8]}"
    account_id = await _create_account(phone, "old-pass-123")
    await _service().change_password(
        account_id, old_password="old-pass-123", new_password="new-pass-456"
    )
    # 新密码可登录、旧密码不可
    resp = await _service().login(phone, "new-pass-456")
    assert resp.account_id == account_id
    with pytest.raises(UnauthorizedError):
        await _service().login(phone, "old-pass-123")


async def test_change_password_wrong_old_password_rejected() -> None:
    phone = f"125{str(uuid.uuid4().int)[:8]}"
    account_id = await _create_account(phone, "right-pass")
    with pytest.raises(UnauthorizedError):
        await _service().change_password(
            account_id, old_password="wrong", new_password="new-pass-456"
        )


async def test_change_password_short_new_password_rejected() -> None:
    phone = f"124{str(uuid.uuid4().int)[:8]}"
    account_id = await _create_account(phone, "old-pass-123")
    with pytest.raises(BadRequestError):
        await _service().change_password(
            account_id, old_password="old-pass-123", new_password="short"
        )


# ---- dedup_clues 按账号隔离（组合主键） ----


async def test_dedup_store_per_account_isolation() -> None:
    store = DedupStore(_DATABASE)
    account_a = str(uuid.uuid4())
    account_b = str(uuid.uuid4())
    clue = {
        "clue_id": "高速背板连接器_20260828",
        "product_keywords": ["高速背板连接器"],
        "target_industry": "数据中心交换机",
        "recommendations": [{"company_name": "A 公司", "status": "已推荐"}],
        "excluded_companies": [],
        "total_found": 1,
        "remaining_pool": 0,
    }
    # 两账号同日同产品：相同 clue_id 互不覆盖（组合键）
    await store.upsert_clue(
        {**clue, "recommendations": [{"company_name": "A", "status": "已推荐"}]}, account_a
    )
    await store.upsert_clue(
        {**clue, "recommendations": [{"company_name": "B", "status": "已推荐"}]}, account_b
    )
    history_a = await store.load_history(account_a)
    history_b = await store.load_history(account_b)
    assert len(history_a["product_clues"]) == 1
    assert len(history_b["product_clues"]) == 1
    rec_a = history_a["product_clues"][0]["recommendations"][0]["company_name"]
    rec_b = history_b["product_clues"][0]["recommendations"][0]["company_name"]
    assert rec_a == "A"
    assert rec_b == "B"  # 相互独立，未被覆盖


# ---- HTTP /auth/login 端点 ----


async def test_http_login_endpoint(
    api_ctx: tuple[object, httpx.AsyncClient],
) -> None:
    _app, client = api_ctx
    phone = f"133{str(uuid.uuid4().int)[:8]}"
    await _create_account(phone, "pw-456")
    ok = await client.post("/api/v1/auth/login", json={"phone": phone, "password": "pw-456"})
    assert ok.status_code == 200
    body = LoginResponse.model_validate(ok.json())
    assert body.token
    assert body.account_id
    bad = await client.post("/api/v1/auth/login", json={"phone": phone, "password": "no"})
    assert bad.status_code == 401


async def test_http_elecnest_login_endpoint(
    api_ctx: tuple[object, httpx.AsyncClient],
) -> None:
    app, client = api_ctx
    # 开启统一登录（共享 settings 对象，AuthService 读同一引用）+ 注入 mock 客户端
    app.state.services.settings.elecnest_sso_enabled = True  # type: ignore[attr-defined]  # 测试直改运行时配置
    app.state.services.auth._elecnest = _mock_elecnest(  # type: ignore[attr-defined]  # 测试注入 mock 客户端
        {"uid": 99001, "username": "wangwu", "nickname": "王五", "phone": "13800000002"}
    )
    ok = await client.post("/api/v1/auth/login/elecnest", json={"token": "sso-token", "uid": 99001})
    assert ok.status_code == 200
    body = LoginResponse.model_validate(ok.json())
    assert body.token
    assert body.account_id
    assert body.name == "王五"
    # 幂等：二次登录同 account_id
    again = await client.post(
        "/api/v1/auth/login/elecnest", json={"token": "sso-token", "uid": 99001}
    )
    assert again.status_code == 200
    assert again.json()["account_id"] == body.account_id


async def test_http_elecnest_login_disabled(
    api_ctx: tuple[object, httpx.AsyncClient],
) -> None:
    _app, client = api_ctx
    # 默认开关关闭 → 400（未启用）
    resp = await client.post("/api/v1/auth/login/elecnest", json={"token": "t", "uid": 1})
    assert resp.status_code == 400


async def test_http_avatar_config(
    api_ctx: tuple[object, httpx.AsyncClient],
) -> None:
    _app, client = api_ctx
    response = await client.get("/api/v1/users/me/avatar-config")
    assert response.status_code == 200
    config = AvatarConfig.model_validate(response.json())
    assert config.max_size_bytes > 0
    assert "png" in config.allowed_extensions


async def test_http_patch_users_me_updates_name(
    api_ctx: tuple[object, httpx.AsyncClient],
) -> None:
    _app, client = api_ctx
    phone = f"123{str(uuid.uuid4().int)[:8]}"
    account_id = await _create_account(phone, "pw")
    headers = _token_for(account_id)
    response = await client.patch("/api/v1/users/me", json={"name": "接口改名"}, headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "接口改名"
    assert body["account_id"] == account_id


async def test_http_patch_users_me_requires_auth(
    api_ctx: tuple[object, httpx.AsyncClient],
) -> None:
    _app, client = api_ctx
    response = await client.patch("/api/v1/users/me", json={"name": "x"})
    assert response.status_code == 401


async def test_http_avatar_upload_sets_avatar(
    api_ctx: tuple[object, httpx.AsyncClient],
) -> None:
    _app, client = api_ctx
    phone = f"122{str(uuid.uuid4().int)[:8]}"
    account_id = await _create_account(phone, "pw")
    headers = _token_for(account_id)
    response = await client.post(
        "/api/v1/users/me/avatar",
        headers=headers,
        files={"file": ("avatar.png", _PNG_BYTES, "image/png")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["avatar"] is not None and body["avatar"].startswith("/files/")
    # 上传后头像预览可读
    preview = await client.get(body["avatar"])
    assert preview.status_code == 200
    assert preview.content == _PNG_BYTES


async def test_http_avatar_upload_rejects_fake_image(
    api_ctx: tuple[object, httpx.AsyncClient],
) -> None:
    _app, client = api_ctx
    phone = f"121{str(uuid.uuid4().int)[:8]}"
    account_id = await _create_account(phone, "pw")
    headers = _token_for(account_id)
    response = await client.post(
        "/api/v1/users/me/avatar",
        headers=headers,
        files={"file": ("fake.png", b"not an image", "image/png")},
    )
    assert response.status_code == 400


async def test_http_change_password(
    api_ctx: tuple[object, httpx.AsyncClient],
) -> None:
    app, client = api_ctx
    phone = f"120{str(uuid.uuid4().int)[:8]}"
    account_id = await _create_account(phone, "old-pass-123")
    headers = _token_for(account_id)
    response = await client.post(
        "/api/v1/users/me/password",
        json={"old_password": "old-pass-123", "new_password": "new-pass-456"},
        headers=headers,
    )
    assert response.status_code == 200
    # 新密码可登录
    assert (
        await client.post("/api/v1/auth/login", json={"phone": phone, "password": "new-pass-456"})
    ).status_code == 200
    # 旧密码不可
    assert (
        await client.post("/api/v1/auth/login", json={"phone": phone, "password": "old-pass-123"})
    ).status_code == 401
    del app  # 仅防未使用告警（无 linter 门禁，保留可读性）


async def test_http_change_password_wrong_old(
    api_ctx: tuple[object, httpx.AsyncClient],
) -> None:
    _app, client = api_ctx
    phone = f"119{str(uuid.uuid4().int)[:8]}"
    account_id = await _create_account(phone, "real-pass")
    headers = _token_for(account_id)
    response = await client.post(
        "/api/v1/users/me/password",
        json={"old_password": "nope", "new_password": "new-pass-456"},
        headers=headers,
    )
    assert response.status_code == 401


# ---- HTTP /users/me/usage/daily（趋势图数据源）----


async def test_http_daily_usage_endpoint(
    api_ctx: tuple[object, httpx.AsyncClient],
) -> None:
    _app, client = api_ctx
    phone = f"118{str(uuid.uuid4().int)[:8]}"
    account_id = await _create_account(phone, "pw", name="张三")
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    cid = uuid.uuid4().hex
    await _insert_message(
        account_id,
        day=today,
        conversation_id=cid,
        prompt=10,
        completion=5,
        total=15,
        cached_read=3,
        cached_write=1,
    )
    await _insert_message(
        account_id,
        day=today,
        conversation_id=cid,
        prompt=20,
        completion=10,
        total=30,
        cached_read=6,
        cached_write=2,
    )

    response = await client.get(
        "/api/v1/users/me/usage/daily",
        params={"days": 7},
        headers=_token_for(account_id),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["account_id"] == account_id
    assert body["name"] == "张三"
    assert body["days"] == 7
    assert len(body["items"]) == 7  # 零填充、每天一条
    assert body["items"][-1]["date"] == today.isoformat()
    assert body["items"][-1]["message_count"] == 2
    assert body["items"][-1]["conversation_count"] == 1  # 同一会话去重
    assert body["items"][-1]["total_tokens"] == 45
    assert body["items"][-1]["cached_read_tokens"] == 9
    assert body["items"][0]["message_count"] == 0  # 无数据日零填充
    assert body["items"][0]["total_tokens"] == 0


async def test_http_daily_usage_requires_auth(
    api_ctx: tuple[object, httpx.AsyncClient],
) -> None:
    _app, client = api_ctx
    response = await client.get("/api/v1/users/me/usage/daily")
    assert response.status_code == 401


async def test_http_daily_usage_defaults_and_bounds(
    api_ctx: tuple[object, httpx.AsyncClient],
) -> None:
    _app, client = api_ctx
    phone = f"117{str(uuid.uuid4().int)[:8]}"
    account_id = await _create_account(phone, "pw")
    headers = _token_for(account_id)
    # 默认 days=30
    ok = await client.get("/api/v1/users/me/usage/daily", headers=headers)
    assert ok.status_code == 200
    assert ok.json()["days"] == 30
    assert len(ok.json()["items"]) == 30
    # 越界 422
    assert (
        await client.get("/api/v1/users/me/usage/daily", params={"days": 0}, headers=headers)
    ).status_code == 422
    assert (
        await client.get("/api/v1/users/me/usage/daily", params={"days": 91}, headers=headers)
    ).status_code == 422
