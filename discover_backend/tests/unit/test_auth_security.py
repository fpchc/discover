"""认证安全单测：Argon2id 密码哈希 + JWT 会话令牌（无网络 / 无 DB）。

覆盖：哈希往返 / 错误密码 / 畸形存量哈希；JWT 签发校验 / 篡改 / 过期 /
缺密钥拒绝。CLAUDE.md §12：时间相关逻辑经配置注入固定，测试幂等。
"""

from __future__ import annotations

import time

import jwt
import pytest
from app.config.settings import Settings
from app.domain.auth.security import JwtService, PasswordHasher
from app.shared.errors.base import ConfigError, UnauthorizedError

_ACCOUNT_ID = "00000000-0000-0000-0000-0000000000aa"
_SECRET = "test-secret-0123456789abcdef0123456789abcdef"


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, jwt_secret_key=_SECRET, **overrides)


# ---- Argon2id 密码哈希 ----


def test_password_hash_roundtrip() -> None:
    hasher = PasswordHasher(_settings())
    encoded = hasher.hash("S3cret!密码")
    assert encoded.startswith("$argon2id$")  # PHC 自含编码（算法/参数/盐/哈希）
    assert "password" not in encoded
    assert hasher.verify(encoded, "S3cret!密码") is True


def test_password_hash_wrong_password_false() -> None:
    hasher = PasswordHasher(_settings())
    encoded = hasher.hash("correct")
    assert hasher.verify(encoded, "wrong") is False


def test_password_hash_malformed_stored_hash_false() -> None:
    """存量畸形哈希视作无效（返回 False，不抛 500）。"""
    hasher = PasswordHasher(_settings())
    assert hasher.verify("not-an-argon2-hash", "any") is False


def test_password_hashes_unique_salt() -> None:
    """同一密码两次哈希结果不同（每次随机盐）。"""
    hasher = PasswordHasher(_settings())
    assert hasher.hash("same") != hasher.hash("same")


# ---- JWT 会话令牌 ----


def test_jwt_encode_decode_roundtrip() -> None:
    svc = JwtService(_settings())
    token = svc.encode(_ACCOUNT_ID)
    assert svc.decode(token) == _ACCOUNT_ID


def test_jwt_encode_includes_platform_claims() -> None:
    """encode 产出平台契约令牌（iss/aud/type=access），可通过平台验签。"""
    svc = JwtService(_settings())
    token = svc.encode(_ACCOUNT_ID)
    claims = svc.decode_platform_token(token)
    assert claims.user_id == _ACCOUNT_ID
    assert claims.user_id != "someone-else"


def test_jwt_tampered_token_rejected() -> None:
    svc = JwtService(_settings())
    token = svc.encode(_ACCOUNT_ID)
    tampered = token[:-4] + ("AAAA" if not token.endswith("AAAA") else "BBBB")
    with pytest.raises(UnauthorizedError):
        svc.decode(tampered)


def test_jwt_expired_token_rejected() -> None:
    """过期令牌拒绝（访问令牌有效期配置为负即立即过期，测试幂等）。"""
    svc = JwtService(_settings(auth_access_token_ttl_seconds=-1))
    token = svc.encode(_ACCOUNT_ID)
    with pytest.raises(UnauthorizedError):
        svc.decode(token)


def test_jwt_lifetime_synced_with_configured_ttl() -> None:
    """本地令牌校验与 AUTH_ACCESS_TOKEN_TTL_SECONDS 同步：exp-iat 超出配置即拒绝。"""
    svc = JwtService(_settings(auth_access_token_ttl_seconds=3600))
    now = int(time.time())
    claims: dict[str, object] = {
        "sub": _ACCOUNT_ID,
        "type": "access",
        "iss": "crm-auth",
        "aud": "crm-backend",
        "iat": now,
    }
    too_long = jwt.encode({**claims, "exp": now + 7200}, _SECRET, algorithm="HS256")
    with pytest.raises(UnauthorizedError):
        svc.decode(too_long)
    in_window = jwt.encode({**claims, "exp": now + 3600}, _SECRET, algorithm="HS256")
    assert svc.decode(in_window) == _ACCOUNT_ID


def test_jwt_missing_secret_rejected_at_construction() -> None:
    """缺失 JWT_SECRET_KEY → 构造即抛 ConfigError（认证必启用，禁默认密钥）。"""
    with pytest.raises(ConfigError):
        JwtService(Settings(_env_file=None))
