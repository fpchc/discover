# 统一认证平台接入说明

> **统一认证接入说明（2026-09-05）**：登录令牌由平台签发，本项目只本地验签。
> **兼容模式（2026-09-07）**：统一认证为主，原本地登录（手机号+密码 / elecnest
> SSO / 刷新 / 登出 / 改密码）**恢复可用**作为兼容回退。
> **统一登录仅作登录映射**——对外标识与数据隔离列保持原结构（本地账号 uuid
> 文本），不引入第二套用户标识。改动半径：认证域（`domain/auth`）+ HTTP 接入
> （`deps.py` / `auth.py`）。

## 1. 目标形态

本项目以**统一认证平台接入方**为主，同时**保留原本地登录作为兼容回退**
（2026-09-07 恢复可用：手机号+密码 / elecnest SSO / 刷新 / 登出 / 改密码）：

| 维度 | 统一认证平台（主） | 原本地登录（兼容回退） |
|---|---|---|
| 登录 | 平台签发令牌，本项目**只验签不解发** | `POST /auth/login`（手机号+密码）/ `POST /auth/login/elecnest`（公司统一登录）签发本地令牌对 |
| 令牌校验 | 本地验签：HS256 + 共享密钥 + `aud` + `iss` + `type=access`（无 Redis / 无网络） | 本地 JWT 验签 + Redis 访问会话存在性（登出/过期即失效） |
| 续期 / 登出 | 平台侧负责，本项目不刷新/不登出平台令牌 | `POST /auth/refresh`（轮换制）/ `POST /auth/logout`（作废访问 + 刷新会话） |
| 用户标识 | 仍为本地 `accounts.id`（uuid 文本）；平台 `user_id`（JWT `sub`）仅登录映射（`auth_user_id`） | 本地 `accounts.id`（uuid 文本） |
| 权限 | 权限码体系（平台 `permission_codes`）——**预留，另行方案** | 本地 `is_system` 超级用户标记 |

受保护接口**兼容两种令牌**：`get_current_account` 经 `AuthService.resolve_current_account`
区分——平台令牌（sub=平台 user_id）按 `auth_user_id` find-or-create 本地账号；
原本地登录令牌（sub=本地账号 uuid）按 id 直查并校验 Redis 访问会话。

## 2. 令牌规格与校验

| 项 | 值 | 配置 |
|---|---|---|
| 算法 | HS256 | `JWT_ALGORITHM`（默认 HS256） |
| 密钥 | 平台共享密钥 `APP_SECRET_KEY` | `JWT_SECRET_KEY` |
| 签发者 `iss` | `crm-auth` | `JWT_ISSUER`（默认 crm-auth） |
| 受众 `aud` | 本项目登记的受众 | `JWT_AUDIENCE`（默认 crm-backend，需在平台 `AUTH_AUDIENCES` 登记） |
| 令牌类型 `type` | 业务接口只收 `access` | — |

校验步骤（全部通过才有效，任一失败 → 401「登录状态已失效，请重新登录」）：

1. 验签：HS256 + `JWT_SECRET_KEY`
2. `exp` 未过期（PyJWT 原生校验）
3. `aud == JWT_AUDIENCE`（PyJWT `audience` 参数原生校验）
4. `iss == JWT_ISSUER`（PyJWT `issuer` 参数原生校验）
5. `type == "access"`（手动校验）

实现：`JwtService.decode_platform_token(token) → PlatformTokenClaims(user_id=sub, sid, jti)`，
见 `app/domain/auth/security.py`。

## 3. 用户标识与数据隔离

**用户标识不变**：对外标识与数据隔离键**恒为本地账号 uuid 文本**
（`str(accounts.id)`）。统一认证只增加登录映射，不改变存值：

| 表 | 列 | 存值 |
|---|---|---|
| `conversations` | `from_account_id` | 本地账号 uuid 文本 |
| `messages` | `created_by` | 本地账号 uuid 文本 |
| `upload_files` | `created_by` | 本地账号 uuid 文本 |
| `dedup_clues` | `created_by` | 本地账号 uuid 文本（组合主键首列） |

上述列保持 `varchar(64)`（兼容历史行，无需区分处理）。

`accounts` 新增 `auth_user_id`（平台 `user_id`，JWT `sub`，唯一索引，存量本地账号
为 `NULL`）仅作**登录映射键**：平台登录按它 find-or-create 本地账号
（`user_type=unified`，默认名「用户{user_id}」），命中后一切操作沿用本地账号
uuid——**不引入第二套用户标识，所有查询仍按用户 id（本地 uuid）区分**。

存量账号接入统一登录：`provision --auth-user-id <id>` 把既有本地账号与平台
`user_id` 绑定（同时可用 `--superuser` 标注管理员），绑定后平台登录命中该本地
账号，历史隔离数据（按本地 uuid 聚合）自然可见，无需重映射。

## 4. 认证链（FastAPI 依赖）

| 依赖 | 行为 |
|---|---|
| `_bearer_token` | 提取 `Authorization: Bearer <token>`；缺失/畸形 → 401 |
| `get_current_account` | 本地验签 → `AuthService.resolve_current_account`：平台令牌（sub=平台 user_id）按 `auth_user_id` `resolve_user` find-or-create；原本地登录令牌（sub=本地账号 uuid）按 id 直查 + 校验 Redis 会话（查无/会话失效 → 401） |
| `get_current_account_id` | 依赖 `get_current_account`，返回**本地账号 uuid 文本**（数据隔离与查询统一按此） |
| `require_superuser` | 本地 `is_system=true` 才放行（管理员经 CLI 绑定 + `--superuser`）；**过渡期占位**，待权限码体系接入后替换 |

`AccountRecord.account_id` 恒为**本地账号 uuid 文本**（统一登录仅映射，无第二标识）。

## 5. 用户信息接口

`GET /users/me` 返回本地资料（`account_id` 为本地账号 uuid，登录来源见
`user_type`）。受「仅本地验签」约束，令牌不含平台侧 `username` /
`permission_codes` / 租户信息；前端用户上下文以平台登录会话为准。首次登录后
可用 `PATCH /users/me` 补昵称。

## 6. 对接检查清单

- [ ] 平台下发共享密钥 → 配置 `JWT_SECRET_KEY`
- [ ] 平台 `AUTH_AUDIENCES` 登记本项目受众 → 配置 `JWT_AUDIENCE`
- [ ] `JWT_ISSUER` 与平台签发者一致（默认 crm-auth）
- [ ] 前端登录/刷新走平台接口，业务请求带 `Authorization: Bearer <access_token>`
- [ ] 管理员账号经 `provision --auth-user-id <id> --superuser` 绑定
- [ ] 存量本地账号接入统一登录：用 `provision --auth-user-id` 绑定（登录映射，历史数据按本地 uuid 自然关联）
