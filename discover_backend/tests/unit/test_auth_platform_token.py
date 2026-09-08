"""统一认证平台令牌校验单测：本地验签（HS256 + aud + iss + type=access）。

CLAUDE.md §12：无网络 / 无 DB；令牌用 PyJWT 直接构造（encode 接口另测于
test_auth_security）。校验矩阵覆盖：正常 / 过期 / aud 不符 / iss 不符 /
type 非 access / 缺 type / 篡改 / 缺 sub / 缺 aud·iss claim。
"""

from __future__ import annotations

import time

import jwt
import pytest
from app.config.settings import Settings
from app.domain.auth.security import JwtService
from app.shared.errors.base import UnauthorizedError

_SECRET = "test-secret-0123456789abcdef0123456789abcdef"
_ISSUER = "crm-auth"
_AUDIENCE = "crm-backend"


def _service() -> JwtService:
    return JwtService(
        Settings(
            _env_file=None,
            jwt_secret_key=_SECRET,
            jwt_issuer=_ISSUER,
            jwt_audience=_AUDIENCE,
        )
    )


def _sign(claims: dict[str, object]) -> str:
    """用共享密钥签发原始 JWT（claims 全由测试控制）。"""
    return jwt.encode(claims, _SECRET, algorithm="HS256")


def _base_claims(**overrides: object) -> dict[str, object]:
    """平台契约完整 claims（sub/type/iss/aud/iat/exp），可覆盖。"""
    now = int(time.time())
    claims: dict[str, object] = {
        "sub": "2",
        "type": "access",
        "iss": _ISSUER,
        "aud": _AUDIENCE,
        "iat": now,
        "exp": now + 3600,
    }
    claims.update(overrides)
    return claims


# ---- 正常路径 ----


def test_valid_platform_token_returns_user_id() -> None:
    svc = _service()
    token = _sign(_base_claims(sid="sess-1", jti="token-1"))
    claims = svc.decode_platform_token(token)
    assert claims.user_id == "2"
    assert claims.sid == "sess-1"
    assert claims.jti == "token-1"


def test_encode_produces_platform_conformant_token() -> None:
    """本项目 encode（测试/回退用）产出的令牌可通过平台验签（iss/aud/type 齐备）。"""
    svc = _service()
    token = svc.encode("2")
    assert svc.decode_platform_token(token).user_id == "2"


# ---- 逐项校验失败 → 401 ----


def test_expired_token_rejected() -> None:
    token = _sign(_base_claims(exp=int(time.time()) - 1))
    with pytest.raises(UnauthorizedError):
        _service().decode_platform_token(token)


def test_wrong_audience_rejected() -> None:
    """aud 不符（跨受众误用）→ 拒。"""
    token = _sign(_base_claims(aud="other-backend"))
    with pytest.raises(UnauthorizedError):
        _service().decode_platform_token(token)


def test_missing_aud_claim_rejected() -> None:
    token = _sign({k: v for k, v in _base_claims().items() if k != "aud"})
    with pytest.raises(UnauthorizedError):
        _service().decode_platform_token(token)


def test_wrong_issuer_rejected() -> None:
    token = _sign(_base_claims(iss="other-auth"))
    with pytest.raises(UnauthorizedError):
        _service().decode_platform_token(token)


def test_missing_issuer_claim_rejected() -> None:
    token = _sign({k: v for k, v in _base_claims().items() if k != "iss"})
    with pytest.raises(UnauthorizedError):
        _service().decode_platform_token(token)


def test_refresh_type_token_rejected() -> None:
    """refresh 令牌不用于业务接口（type 必须为 access）。"""
    token = _sign(_base_claims(type="refresh"))
    with pytest.raises(UnauthorizedError):
        _service().decode_platform_token(token)


def test_missing_type_claim_rejected() -> None:
    token = _sign({k: v for k, v in _base_claims().items() if k != "type"})
    with pytest.raises(UnauthorizedError):
        _service().decode_platform_token(token)


def test_tampered_signature_rejected() -> None:
    token = _sign(_base_claims())
    tampered = token[:-4] + ("AAAA" if not token.endswith("AAAA") else "BBBB")
    with pytest.raises(UnauthorizedError):
        _service().decode_platform_token(tampered)


def test_missing_sub_rejected() -> None:
    token = _sign({k: v for k, v in _base_claims().items() if k != "sub"})
    with pytest.raises(UnauthorizedError):
        _service().decode_platform_token(token)


def test_empty_sub_rejected() -> None:
    token = _sign(_base_claims(sub=""))
    with pytest.raises(UnauthorizedError):
        _service().decode_platform_token(token)


# ---- 配置：issuer/audience 从 Settings 注入（配置驱动） ----


def test_custom_issuer_audience_from_settings() -> None:
    """iss/aud 全部配置驱动：自定义值时按新值验签（CLAUDE.md §5）。"""
    svc = JwtService(
        Settings(
            _env_file=None,
            jwt_secret_key=_SECRET,
            jwt_issuer="custom-iss",
            jwt_audience="custom-aud",
        )
    )
    token = _sign(_base_claims(iss="custom-iss", aud="custom-aud"))
    assert svc.decode_platform_token(token).user_id == "2"
