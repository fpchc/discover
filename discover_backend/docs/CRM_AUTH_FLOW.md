# CRM 令牌授权接入流程（只做授权，不做登录）

> **适用场景**：对接方（CRM / 前端 / 联调同学）需要理解「携带 CRM 签发的令牌访问本平台业务接口」这条链路的完整行为——令牌怎么校验、用户是谁、账号从哪来、失败时返回什么。
> **不适用场景**：本文不描述本平台的登录接口（手机号+密码、token+uid 统一登录）与其 Redis 会话/刷新/登出机制；那两条属于「本平台自己发令牌」，见 `docs/ARCHITECTURE.md` 账号认证条目。
> **职责边界与权威来源**：本文是流程说明，事实源为代码 `app/domain/auth/`（`security.py` / `service.py`）+ `app/interfaces/http/deps.py`。行为有出入时以代码为准，并回改本文。

平台共支持三套进入方式，**本文只讲第三套**：

| # | 进入方式 | 入口 | 谁签发令牌 | 本平台是否建会话（Redis） | 本文 |
|---|---|---|---|---|---|
| 1 | 手机号 + 密码 | `POST /auth/login` | 本平台 | 是（访问 + 刷新会话） | 不涉及 |
| 2 | token + uid 统一登录 | `POST /auth/login/elecnest` | 本平台 | 是（访问 + 刷新会话） | 不涉及 |
| 3 | **CRM 令牌直连** | 无登录入口，直接带令牌调业务接口 | **CRM（crm-auth）** | **否** | **本文** |

第三套的定位一句话：**本平台不签发、不刷新、不登出 CRM 令牌，只做「验签 + 账号映射 + 放行」**。用户身份由 CRM 令牌决定，本平台仅在首次访问时按平台 `user_id` 落一条本地账号记录用于数据归属。

---

## 1. 令牌契约

CRM 用共享密钥签发的 JWT（HS256），本平台**只验签**：

| 字段 | 要求 | 说明 |
|---|---|---|
| `alg` | `HS256` | 与 `JWT_ALGORITHM` 一致 |
| 签名密钥 | 平台共享密钥（CRM 侧 `APP_SECRET_KEY`） | 本平台经环境注入 `JWT_SECRET_KEY`；缺失则应用启动即失败（`ConfigError`），无默认值 |
| `iss` | `crm-auth` | 与 `JWT_ISSUER` 比对，不符即拒 |
| `aud` | `crm-backend` | 与 `JWT_AUDIENCE` 比对；需已在 CRM 侧 `AUTH_AUDIENCES` 登记本项目受众，否则跨受众误用会被拒 |
| `type` | `access` | `refresh` 令牌不可用于业务接口 |
| `exp` | 未过期 | 有效期由 CRM 签发时决定，本平台**不施加本地 TTL** |
| `sub` | 非空字符串 | **CRM 用户标识**，本平台唯一使用的身份字段（下面统称平台 `user_id`） |
| `sid` / `jti` | 可选 | 本平台会解析出来，但当前不参与任何校验或存储 |

校验项（**全部通过才放行**，任一失败即 401）：
验签 → `exp` → `aud` → `iss` → `type == "access"` → `sub` 非空。

实现：`JwtService.decode_platform_token()`（`app/domain/auth/security.py`），返回 `PlatformTokenClaims(user_id, sid, jti)`。

> **无网络、无 Redis**：整个校验过程是本地的纯计算，不会回调 CRM，也不读写 Redis。

---

## 2. 每请求处理流程

客户端每次调用业务接口都携带：

```http
Authorization: Bearer <CRM 签发的 access_token>
```

处理链路（`app/interfaces/http/deps.py` → `app/domain/auth/service.py`）：

```
客户端 ── Bearer <CRM token> ──► 业务接口
                                    │
  ①  提取令牌  _bearer_token()        │  缺失/非 Bearer/空串 → 401「未登录」
                                    ▼
  ②  验签 + 五项校验  JwtService.decode_platform_token()
     失败 → 401「登录状态已失效，请重新登录」
     type≠access / sub 缺失 → 401「登录状态非法」
                                    ▼
  ③  得到平台 user_id（JWT sub）
                                    ▼
  ④  先按「本地账号 uuid」试解  get_account(user_id)
     ├─ 命中 → 视为本地登录令牌：额外校验 Redis 访问会话（本文不涉及）
     └─ 未命中（正常情况）↓
                                    ▼
  ⑤  账号映射 find-or-create  resolve_user(user_id)
     · 按 accounts.auth_user_id = user_id 查库
     · 查不到 → 新建本地账号（见 §3），user_type=unified
     · 并发首访撞唯一索引 → 回滚后二次查询兜底（幂等）
     · 仍失败 → 401「账号不存在」
                                    ▼
  ⑥  得到本地账号 AccountRecord
                                    ▼
  ⑦  get_current_account_id() → 本地账号 uuid 文本
                                    ▼
  ⑧  业务层按该 uuid 查询、过滤、归属校验
```

要点：

- **每个请求会执行一次 `accounts` 查询**（步骤 ⑤ 的映射查询）。这是无状态鉴权的代价，换来的是不依赖 Redis 会话、可水平扩展、CRM 侧登出即失效（令牌一过期本平台立刻不再认）。
- **Redis 在这条链路上完全不参与**：CRM 令牌的过期判断只看 JWT `exp`。因此 Redis 故障不会影响 CRM 令牌的业务请求（对比第 1、2 套登录：Redis 是不可用即拒的硬依赖）。
- 本平台**不调用** CRM 的用户信息接口。与第 2 套（token+uid 会去换用户资料）不同，第三套拿不到平台侧昵称/头像/权限码，用户信息一律取本地记录。

---

## 3. 账号映射与用户信息

### 3.1 首次访问自动建档

平台 `user_id` 不在本地时，自动创建一条 `accounts` 记录（`AuthService.resolve_user`）：

| 列 | 写入值 | 备注 |
|---|---|---|
| `id` | 新 uuid（本地主键） | **对外标识、数据隔离键恒为这个 uuid** |
| `auth_user_id` | 平台 `user_id` | 唯一索引，登录映射键 |
| `name` | `用户{user_id}` | 首次访问的默认显示名 |
| `username` | `unified_{user_id}`（超长截断 64） | 唯一索引，仅信息用途 |
| `user_type` | `unified` | 标记「来源 = CRM 授权」 |
| `status` | `active` | |
| `phone` | `""` | |
| `avatar` | `NULL` | 需用户自行上传 |
| `last_login_at`/`last_active_at` | 首次访问时写入（best-effort） | |

注意事项：
- **建档是幂等的**：同一个平台 `user_id` 并发首访也只会有一条账号记录（唯一索引 + 冲突回滚后二次查询）。
- **账号被封禁的处理**：`status != active` 的账号，在 `resolve_user` 已有记录的分支上**不额外校验**（该状态校验只在手机号登录与 elecnest 登录路径生效）。需要禁用某账号时，当前应按「不为其绑定/删除映射」或运维直接停用处理，不要仅依赖 `status` 字段。

### 3.2 用户信息接口

| 接口 | 返回 | 说明 |
|---|---|---|
| `GET /api/v1/users/me` | 本地 `AccountRecord` | `account_id` 恒为本地 uuid 文本；含 `name` / `phone` / `avatar` / `status` / `is_system` / `user_type=unified` / 时间戳 |
| `PATCH /api/v1/users/me` | 同上 | 仅支持改昵称 `name`（白名单字段，防越权改 `phone` 等） |
| `POST /api/v1/users/me/avatar` | 同上 | 上传头像，校验严于通用上传（仅图片扩展名 + magic bytes + 体积/边长限制） |
| `GET /api/v1/users/me/avatar-config` | 头像约束 | 公开接口，无需令牌 |

**不存在的能力**（不要按登录体系理解）：
- 无注册接口（账号由平台 `user_id` 自动映射或运维 CLI 预置）。
- `POST /api/v1/users/me/password` 对 CRM 授权账号不可用：本地无密码哈希，返回 400「当前账号未设置密码，无法修改」。
- `POST /api/v1/auth/refresh`、`POST /api/v1/auth/logout` 是**本平台自签令牌**的续期/登出接口。拿 CRM 令牌调 `refresh` 会 401（本地 Redis 无此刷新会话）；调 `logout` 会返回 204 但实际什么也没作废（幂等删除不存在的 key）。CRM 令牌的续期与登出**由 CRM 负责**。

### 3.3 管理员（超级用户）

`GET /api/v1/users`（全量账号 token 用量）要求 `is_system=true`。CRM 令牌不携带权限码，因此**平台侧的管理员身份不会自动映射**；需要把某个平台 `user_id` 绑定到本地管理员账号（运维 CLI）：

```bash
python -m app.domain.auth.provision --phone <已有账号手机号> --auth-user-id <平台 user_id> --superuser
```

绑定后，该平台 `user_id` 登录即命中这条本地账号，历史数据（按本地 uuid 聚合）自然延续。

---

## 4. 数据隔离

所有业务数据按**本地账号 uuid 文本**归属，CRM 授权链与其它两套登录共用同一口径，不引入第二套用户标识：

| 表 | 列 | 存值 |
|---|---|---|
| `conversations` | `from_account_id` | 本地账号 uuid |
| `messages` | `created_by` | 本地账号 uuid |
| `upload_files` | `created_by` | 本地账号 uuid |
| `dedup_clues` | `created_by` | 本地账号 uuid（组合主键首列） |

会话列表 / 消息 / 删除按账号过滤，跨账号一律 404（不泄露存在性）；token 用量按 `created_by` 聚合。

---

## 5. 受保护接口清单

均为 `/api/v1` 前缀，均接受 CRM 令牌：

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/chat-messages` | 对话（流式 SSE / 阻塞 JSON） |
| POST | `/chat-messages/{conversation_id}/stop` | 停止进行中回合 |
| GET | `/conversations` | 当前账号会话列表 |
| GET | `/conversations/{conversation_id}/messages` | 会话消息 |
| DELETE | `/conversations/{conversation_id}` | 软删除会话 |
| POST | `/files/upload` | 上传文件（归属当前账号） |
| GET/PATCH | `/users/me` | 当前账号资料 |
| POST | `/users/me/avatar` | 更换头像 |
| POST | `/users/me/password` | 改密码（CRM 授权账号不可用，见 §3.2） |
| GET | `/users/me/usage`、`/users/me/usage/daily` | token 用量 |
| GET | `/users` | 全量用量（仅 `is_system`） |

无需令牌的公开接口：`GET /assistants`、`GET /files/upload`（上传限制配置）、`GET /files/{file_id}/preview`、`GET /users/me/avatar-config`。

---

## 6. 错误契约

错误响应统一形状（中间件 `app/interfaces/middleware/exceptions.py`）：

```json
{ "error": { "category": "auth", "message": "登录状态已失效，请重新登录" } }
```

401（`category = "auth"`）的文案与触发条件：

| 文案 | 触发条件 |
|---|---|
| `未登录` | 无 `Authorization` 头、非 `Bearer` 方案、令牌为空 |
| `登录状态已失效，请重新登录` | 验签失败 / 已过期 / `aud`、`iss` 不符 / 缺 `aud`·`iss` claim |
| `登录状态非法` | `type != "access"`、`type` 缺失、`sub` 缺失或为空 |
| `账号不存在` | 账号映射建档失败（唯一冲突且二次查询仍为空） |

403（`category = "denied"`）：`需要超级用户权限`（非管理员访问 `GET /users`）。
其它：跨账号资源一律 404；请求体非法 400。错误信息经脱敏（不泄露内部细节），日志中不记录令牌与请求体。

---

## 7. 配置项

| 环境变量 | 默认 | 本链路中的作用 |
|---|---|---|
| `JWT_SECRET_KEY` | 无（必填） | 与 CRM 共享的 HS256 密钥；**缺失应用启动失败** |
| `JWT_ALGORITHM` | `HS256` | 签名算法 |
| `JWT_ISSUER` | `crm-auth` | 期望的签发者 |
| `JWT_AUDIENCE` | `crm-backend` | 本平台登记的受众（需 CRM 侧 `AUTH_AUDIENCES` 登记） |
| `AUTH_ACCESS_TOKEN_TTL_SECONDS` | `604800` | **对 CRM 令牌不生效**，仅用于本平台自签令牌 |
| `REDIS_URL` 等 | — | 本链路不使用 |

---

## 8. 边界与注意

1. **不查 Redis**：CRM 令牌的有效期由 JWT `exp` 单独决定；CRM 侧「提前失效令牌」（改密码、踢下线）在本平台**不会立即生效**，最长滞后到 `exp`。若业务要求即时失效，需要另加黑名单/会话校验方案（当前未实现）。
2. **平台 `user_id` 与本地 uuid 的命名空间是隐性前提**：鉴权时先按 `sub` 试解本地账号 uuid（`service.py: resolve_current_account`），所以若 CRM 的 `user_id` 恰好等于某个本地账号 uuid，该请求会被当成「本地登录令牌」处理，从而额外要求 Redis 会话并可能 401。正常数字/业务 ID 形态的 `user_id` 不会命中，但对接时不要用 uuid 形态的平台 ID。
3. **权限码体系未接入**：CRM 令牌里的权限信息本平台不解码，`require_superuser` 用的是本地 `is_system` 占位。
4. **无服务端登出**：用户在前端清掉本地令牌即退出；服务端不持有该用户任何会话状态。
5. **每请求一次 DB 查询**：账号映射查询是这条链路唯一的额外开销。

---

## 9. 对接检查清单

- [ ] CRM 侧下发共享密钥 → 本平台配置 `JWT_SECRET_KEY`（缺失启动即失败）
- [ ] CRM 侧 `AUTH_AUDIENCES` 登记本平台受众 → 本平台配置 `JWT_AUDIENCE`（默认 `crm-backend`）
- [ ] 确认 CRM 签发者与本平台 `JWT_ISSUER` 一致（默认 `crm-auth`）
- [ ] 确认 CRM 令牌含 `iss` / `aud` / `type=access` / 非空 `sub`（缺任一项本平台一律 401）
- [ ] 前端：登录/续期/登出全部走 CRM，业务请求带 `Authorization: Bearer <access_token>`
- [ ] 前端：收到 401 文案「登录状态已失效，请重新登录」时清本地令牌并回 CRM 登录页
- [ ] 管理员账号：用 `provision --auth-user-id <平台 user_id> --superuser` 绑定（平台管理员身份不会自动映射）
- [ ] 存量本地账号接入：用 `provision --phone <手机号> --auth-user-id <平台 user_id>` 绑定，历史数据按本地 uuid 自然延续

---

## 10. 排障速查

| 现象 | 排查方向 |
|---|---|
| 全部请求 401「登录状态已失效」 | `JWT_SECRET_KEY` 是否与 CRM 共享密钥一致（错一位即验签失败）；令牌是否已过期 |
| 部分环境 401、`aud`/`iss` 报错 | `JWT_AUDIENCE` / `JWT_ISSUER` 与 CRM 侧实际签发值不一致；受众未在 CRM `AUTH_AUDIENCES` 登记 |
| 401「登录状态非法」 | 令牌 `type` 不是 `access`（拿到了刷新令牌），或 `sub` 为空 |
| 每次访问都新建账号 | `auth_user_id` 唯一索引未建（检查 Alembic 迁移 `c7d8e9f0a1b2_add_accounts_auth_user_id_widen_account_columns`） |
| 管理员接口 403 | 该平台 `user_id` 尚未经 CLI 绑定 `--superuser` |
| 改密码 400 | CRM 授权账号本地无密码哈希，属预期行为（§3.2） |
| Redis 挂掉后业务仍可用 | 符合预期：本链路不依赖 Redis；受影响的是第 1、2 套登录 |

---

## 11. 代码索引

| 位置 | 职责 |
|---|---|
| `app/interfaces/http/deps.py` | `_bearer_token` 提取、`get_current_account` / `get_current_account_id` / `require_superuser` |
| `app/domain/auth/security.py` | `JwtService.decode_platform_token`（验签 + 五项校验） |
| `app/domain/auth/service.py` | `validate_platform_token`（取 `user_id`）、`resolve_current_account`（区分两种令牌）、`resolve_user`（find-or-create 本地账号） |
| `app/interfaces/schemas/auth.py` | `PlatformTokenClaims`、`AccountRecord`、`UserType.unified` |
| `app/infrastructure/database/models.py` | `Account`（`auth_user_id` 唯一索引、`user_type`） |
| `app/interfaces/middleware/exceptions.py` | 统一错误响应形状与状态码映射 |
| `tests/unit/test_auth_platform_token.py` | 校验矩阵单测（正常 / 过期 / aud / iss / type / 篡改 / 缺 sub / 缺 aud·iss） |
