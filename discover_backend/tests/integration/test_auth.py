"""账号认证集成测试——依赖本地 PostgreSQL。

覆盖：AuthService 登录/账号/用量、dedup_clues 按账号隔离（组合键）、
HTTP /auth/login 端点。迁移须已应用（alembic upgrade head）。
"""

from __future__ import annotations

import uuid

import httpx
import pytest
import pytest_asyncio
from app.config.settings import Settings
from app.db.engine import Database
from app.db.models import Account
from app.errors.base import UnauthorizedError
from app.repositories.dedup import DedupStore
from app.schemas.auth import LoginResponse
from app.schemas.conversations import TurnRecord, TurnUsage
from app.services.auth import AuthService
from app.services.auth_security import PasswordHasher
from app.services.conversations import ConversationService

_DATABASE = Database(Settings(_env_file=None))
_SECRET = "test-secret-0123456789abcdef0123456789abcdef"


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _dispose_database() -> None:
    yield
    await _DATABASE.dispose()


def _settings() -> Settings:
    return Settings(_env_file=None, jwt_secret_key=_SECRET)


def _service() -> AuthService:
    return AuthService(_settings(), _DATABASE, ConversationService(_DATABASE))


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
