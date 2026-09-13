# HTTP 路由登录声明规范

> **适用场景**：新增或调整 FastAPI 路由、判断某条接口是否对外公开、排查「这条接口需要登录吗 / 为什么没鉴权就进来了 / 为什么返回 401」时读本文。
> **不适用场景**：令牌校验算法、账号映射与会话语义（见 `docs/CRM_AUTH_FLOW.md`、`app/domain/identity/` 与 `app/application/identity/`）；登录 / 刷新 / 登出业务逻辑；SSE 帧契约（见 `specs/sse-streaming-spec.md`）。
> **职责边界与权威来源**：权威来源为 `app/interfaces/http/auth_guard.py`（声明与注入）与 `app/interfaces/http/deps.py`（鉴权实现）。本文规定「路由如何声明守卫、守卫如何被执行与校验」，两处代码与本文不一致时以代码为准并回改本文。

## 1. 三个守卫

每条 `/api/v1` 路由必须且只能声明一个守卫，写在路由装饰器**下方**：

| 守卫 | 语义 | 注入依赖 | 典型路由 |
|---|---|---|---|
| `@login_required` | 必须登录；令牌非法 / 过期 / 登出 → 401 统一错误体 | `get_current_account` | `/chat-messages`、`/conversations`、`/users/me` |
| `@bearer_required` | 只要求 `Authorization: Bearer <token>` 存在，不解析身份 | `get_bearer_token` | `/auth/logout`（幂等登出） |
| `@public(reason="...")` | 无需登录；`reason` 为必填公开理由 | 无 | `/auth/login`、`/auth/refresh`、`/assistants`、`/files/upload`（GET 配置） |

`@public` 的 `reason` 不是注释而是契约字段：空串直接 `ValueError`，评审与排查时即可看出「为什么它可以不登录」。

## 2. 顺序约定（装饰器自下而上执行）

```python
@router.get("/users/me")      # 后执行：注册路由，LoginRoute 读取标记并注入依赖
@login_required               # 先执行：在端点函数上打标记
async def current_account(...): ...
```

标记写在 `@router` 上方时，路由已构造完毕、依赖未注入，属于**静默失效**。该情形由 `verify_route_guards` 在应用装配期直接报错阻断启动，不会带到线上。

## 3. 执行机制

- 装饰器**不包装**端点函数：FastAPI 按签名做依赖注入与 OpenAPI 生成，`functools.wraps` 包装会让守卫拿不到请求对象，也让 401 错误体脱离 `ExceptionHandlingMiddleware`。
- `LoginRoute`（`APIRoute` 子类）在路由构造时把标记翻译为 `Depends(...)`；每个 `APIRouter` 必须写 `route_class=LoginRoute`。
- 鉴权只有一套实现：守卫注入的 `get_current_account` 与各路由签名内的 `Depends(get_current_account_id)` / `require_superuser` 是同一依赖链，FastAPI 依赖缓存保证**同一请求只验签一次**。
- 鉴权先于请求体 / 查询参数校验（无令牌的空 body 请求返回 401，而不是 422）。
- 受保护路由在 OpenAPI 中自动带 `401` 响应声明（纯文档收益，便于前端识别）。

## 4. 装配期校验与测试

- `verify_route_guards(routers)` 在 `app/bootstrap/application.py::_register_routes` 中调用：逐条路由校验「恰好一个守卫标记」且「标记与鉴权依赖一致」，违规一次性列出并 `RuntimeError` 阻断启动。
- `tests/unit/test_route_auth_contract.py` 是防腐层：除结构校验外，还遍历真实路由表做 HTTP 行为验证——受保护路由匿名请求 401、公开路由不拦、鉴权先于参数校验、单请求只解析一次账号。
- 守卫清单快照（方法 + 路径 → 守卫）在该测试中固化：新增路由必须同步登记，鉴权变更必须留下 diff。

## 5. 本规范专属检查

1. 新增路由是否写了守卫？漏写 → `verify_route_guards` 报错、契约测试失败。
2. `@login_required` 是否写在 `@router` 下方？顺序写反同样失败。
3. 声明 `@public` 的路由，`reason` 是否说清了公开理由？签名里是否误挂了鉴权依赖？
4. 路由是否需要账号（`account_id`）？需要就保留签名内 `Depends(get_current_account_id)`，不要手写解析。
5. 改动后执行：`ruff format` + `ruff check` 变更文件、`pytest tests/unit`、`mypy`。
