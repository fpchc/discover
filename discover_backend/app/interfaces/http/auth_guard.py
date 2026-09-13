"""路由登录校验声明层：`@login_required` / `@bearer_required` / `@public`。

为什么不用 Flask-Login 那种「包装视图并直接返回 Response」的写法（本机实测）：

- FastAPI 按端点签名做依赖注入；`functools.wraps` 包装后框架仍按被包装函数
  的签名注入参数，包装函数自己声明的 `request: Request` 拿不到注入（实测 500），
  守卫在包装层拿不到请求对象；
- 包装层直接返回 401 Response 会绕开 `ExceptionHandlingMiddleware`，错误体要
  重复实现一遍；换成抛裸异常又变成 500。

因此保留 `@login_required` 的用法形态（贴在路由函数上、一眼可见、可全局检索），
把执行交给 FastAPI 依赖：装饰器打标记 → `LoginRoute` 注册路由时注入
`Depends(get_current_account)`。与既有鉴权同一实现、同一错误体；FastAPI 依赖缓存
保证同一请求只验签一次（路由级依赖与签名内 Depends 命中同一缓存键，实测 1 次）。

标记必须写在 `@router.get/post/...` **下方**（装饰器自下而上执行：先打标记、
后注册路由）。写反不会静默放行：`verify_route_guards` 在装配期直接报错。
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Iterable, Iterator, Mapping
from types import MappingProxyType
from typing import Any, Final

from fastapi import APIRouter, Depends
from fastapi.routing import APIRoute

from app.interfaces.http.deps import (
    get_bearer_token,
    get_current_account,
    get_current_account_id,
    require_superuser,
)

LOGIN_REQUIRED: Final[str] = "__login_required__"
BEARER_REQUIRED: Final[str] = "__bearer_required__"
PUBLIC: Final[str] = "__public_route__"

# 标记 → 注入依赖（策略表）；新增一种守卫只加一行
_GUARDS: Final[Mapping[str, Callable[..., object]]] = MappingProxyType(
    {LOGIN_REQUIRED: get_current_account, BEARER_REQUIRED: get_bearer_token}
)
_LABELS: Final[Mapping[str, str]] = MappingProxyType(
    {LOGIN_REQUIRED: "login_required", BEARER_REQUIRED: "bearer_required", PUBLIC: "public"}
)
_ALL_MARKERS: Final[tuple[str, ...]] = (*_GUARDS, PUBLIC)
# 项目内鉴权依赖全集：判定「标记与依赖是否一致」（含签名内声明，如 require_superuser）
_AUTH_CALLS: Final[frozenset[Callable[..., object]]] = frozenset(
    {get_current_account, get_current_account_id, require_superuser, get_bearer_token}
)


def login_required[**P, R](endpoint: Callable[P, R]) -> Callable[P, R]:
    """声明该路由必须登录；未携带有效令牌 → 401（统一错误体）。

    用法（必须写在路由装饰器下方）::

        @router.get("/users/me")
        @login_required
        async def current_account(...) -> AccountRecord: ...
    """
    return _mark(endpoint, LOGIN_REQUIRED)


def bearer_required[**P, R](endpoint: Callable[P, R]) -> Callable[P, R]:
    """声明该路由只要求 `Authorization: Bearer <token>` 存在（不解析身份）。

    登出这类幂等场景用：无 Bearer → 401，token 本身不作校验。
    """
    return _mark(endpoint, BEARER_REQUIRED)


def public[**P, R](reason: str) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """声明该路由无需登录；reason 为必填公开理由（进代码，便于评审与排查）。"""
    if not reason.strip():
        raise ValueError("@public 必须给出非空公开理由")
    return lambda endpoint: _mark(endpoint, PUBLIC, reason.strip())


def _mark[**P, R](endpoint: Callable[P, R], marker: str, value: object = True) -> Callable[P, R]:
    """在端点函数上打标记（本模块是唯一写入点）。"""
    is_async = inspect.iscoroutinefunction(endpoint)
    if not is_async:
        raise TypeError("路由守卫装饰器只能用于 async def 路由函数")
    setattr(endpoint, marker, value)
    return endpoint


class LoginRoute(APIRoute):
    """把装饰器标记翻译为 FastAPI 鉴权依赖的路由类（唯一执行注入点）。

    每个 APIRouter 都用 `route_class=LoginRoute` 构造；漏写会让标记失效，
    `verify_route_guards` 会在装配期发现并阻断启动。
    """

    def __init__(
        self,
        path: str,
        endpoint: Callable[..., Any],
        # pragma: 简化 — FastAPI APIRoute 的 20+ 构造参数，逐一声明属过度设计
        **kwargs: Any,  # noqa: ANN401
    ) -> None:
        marker = _guard_marker(endpoint)
        if marker is not None:
            responses = dict(kwargs.get("responses") or {})
            responses.setdefault(401, {"description": "未登录或令牌失效"})
            guard = Depends(_GUARDS[marker])
            kwargs["dependencies"] = [*(kwargs.get("dependencies") or []), guard]
            kwargs["responses"] = responses
        super().__init__(path, endpoint, **kwargs)


def _guard_marker(endpoint: object) -> str | None:
    for marker in _GUARDS:
        if getattr(endpoint, marker, None):
            return marker
    return None


def declared_guards(route: APIRoute) -> tuple[str, ...]:
    """路由声明的守卫名（login_required / bearer_required / public），供校验与排查。"""
    return tuple(_LABELS[m] for m in _ALL_MARKERS if getattr(route.endpoint, m, None))


def _has_guard_dependency(route: APIRoute) -> bool:
    """路由依赖树是否含本项目鉴权依赖（含签名内声明，如 require_superuser）。"""
    return any(sub.call in _AUTH_CALLS for sub in route.dependant.dependencies)


def _iter_api_routes(router: APIRouter) -> Iterator[APIRoute]:
    return (route for route in router.routes if isinstance(route, APIRoute))


def verify_route_guards(routers: Iterable[APIRouter]) -> None:
    """装配期校验：每条路由恰好一个标记，且标记与鉴权依赖一致。

    漏标、装饰器写到 `@router` 上方（标记存在但依赖未注入）、公开路由签名里误挂
    鉴权，都在这里一次性列出并阻断启动。
    """
    problems: list[str] = []
    for router in routers:
        for route in _iter_api_routes(router):
            label = f"{'/'.join(sorted(route.methods or []))} {route.path}"
            guards = declared_guards(route)
            if len(guards) != 1:
                problems.append(f"{label}: 需且仅需一个标记，实际 {list(guards) or ['无']}")
            elif (_guard_marker(route.endpoint) is not None) != _has_guard_dependency(route):
                problems.append(f"{label}: 标记 {guards[0]} 与鉴权依赖不一致（检查装饰器顺序）")
    if problems:
        raise RuntimeError("路由登录声明校验失败：\n" + "\n".join(problems))


__all__ = [
    "LoginRoute",
    "bearer_required",
    "declared_guards",
    "login_required",
    "public",
    "verify_route_guards",
]
