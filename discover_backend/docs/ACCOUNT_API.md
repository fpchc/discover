# 账号认证与数据隔离 API 文档

> 2026-08-28 新增，2026-08-29 补齐刷新/登出/资料维护/每日用量。平台引入账号体系
> （手机号 + 密码登录，JWT 会话：访问令牌 + 刷新令牌轮换），并对既有数据接口做
> **账号隔离**。此前所有接口无鉴权；本次起除特殊说明外**数据接口一律需请求头
> `Authorization: Bearer <JWT>`**。所有接口前缀 `/api/v1`；请求/响应均为 JSON。
> 错误统一 `{detail: <message>}`（参数校验失败为 FastAPI 默认 422 形状）。

## 目录

- [0. 认证流程与通用约定](#0-认证流程与通用约定)
- [1. 认证接口](#1-认证接口)
  - [1.1 登录 `POST /auth/login`](#11-登录-post-authlogin)
  - [1.2 统一登录 `POST /auth/login/elecnest`](#12-统一登录-post-authloginelecnest)
  - [1.3 刷新令牌 `POST /auth/refresh`](#13-刷新令牌-post-authrefresh)
  - [1.4 登出 `POST /auth/logout`](#14-登出-post-authlogout)
  - [1.5 当前账号 `GET /users/me`](#15-当前账号-get-usersme)
  - [1.6 当前账号用量 `GET /users/me/usage`](#16-当前账号用量-get-usersmeusage)
  - [1.7 每日用量 `GET /users/me/usage/daily`](#17-每日用量-get-usersmeusagedaily)
  - [1.8 头像上传限制 `GET /users/me/avatar-config`](#18-头像上传限制-get-usersmeavatar-config)
  - [1.9 更新账号 `PATCH /users/me`](#19-更新账号-patch-usersme)
  - [1.10 更换头像 `POST /users/me/avatar`](#110-更换头像-post-usersmeavatar)
  - [1.11 修改密码 `POST /users/me/password`](#111-修改密码-post-usersmepassword)
  - [1.12 全量账号用量 `GET /users`（超级用户）](#112-全量账号用量-get-users超级用户)
- [2. 调整接口（接入认证 + 账号隔离）](#2-调整接口接入认证--账号隔离)
- [3. 保持公开的接口](#3-保持公开的接口)
- [4. 数据隔离语义](#4-数据隔离语义)
- [5. 账号预置](#5-账号预置)
- [6. 错误与状态码速查](#6-错误与状态码速查)

---

## 0. 认证流程与通用约定

1. 手机号 + 密码调 `POST /api/v1/auth/login`，成功返回**令牌对**：JWT 访问令牌
   （HS256，`sub=account_id`）+ 不透明刷新令牌
2. 后续所有受保护请求头带 `Authorization: Bearer <token>`
3. 访问令牌默认 **1 天**（`AUTH_ACCESS_TOKEN_TTL_SECONDS`）；无效/过期/缺失 → `401`
4. 刷新令牌默认 **7 天**（`AUTH_REFRESH_TOKEN_TTL_SECONDS`）；到期前用
   `POST /api/v1/auth/refresh` 换新令牌对（**轮换制**，旧刷新令牌一次性作废）
5. 登出调 `POST /api/v1/auth/logout`，服务端作废当前访问 + 刷新令牌（幂等）
6. 登录失败统一 `401 手机号或密码错误`（防账号枚举）；非超级用户访问管理接口 → `403`

| 状态码 | 含义 |
|---|---|
| `401` | 未登录 / 令牌无效过期 / 刷新令牌失效 / 登录凭据错误 / 账号不存在 |
| `403` | 已认证但无权限（如非 `is_system` 访问 `GET /users`） |

---

## 1. 认证接口

### 1.1 登录 `POST /auth/login`

| 参数 | 位置 | 类型 | 说明 |
|---|---|---|---|
| `phone` | body | string | 登录手机号（预置账号时指定） |
| `password` | body | string | 登录密码 |

**请求**

```json
{ "phone": "13800138001", "password": "eda365123456" }
```

**响应 200**：`LoginResponse`

```json
{
  "account_id": "3f2a9c8e-…-d1b4",
  "token": "eyJhbGciOiJIUzI1NiIs…",
  "refresh_token": "…（不透明随机串，仅 /auth/refresh 用）",
  "expires_in": 86400,
  "name": "张三"
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `token` | string | 访问令牌（请求头 `Authorization: Bearer <token>` 认证用） |
| `refresh_token` | string | 刷新令牌（仅 `/auth/refresh` 用；轮换制，一次性） |
| `expires_in` | int | 访问令牌剩余秒数（前端预刷新参考） |
| `name` | string? | 显示名 |

**失败 401**：`{detail: "手机号或密码错误"}` / `{detail: "账号不可用"}`

### 1.2 统一登录 `POST /auth/login/elecnest`

公司统一登录（elecnest SSO）。开关 `ELECNEST_SSO_ENABLED=false` 时返回
`400`（未启用）。前端从公司统一登录体系拿 `token + uid` 后调本接口：后端用
`token + uid` 调统一登录用户信息接口（`ELECNEST_GET_USER_INFO_URL`，默认
`https://id.elecnest.cn/api/login/getUserInfo`）换取用户资料 → **本地注册
（find-or-create by `elecnest_uid`）** → 标记 `user_type=elecnest` → 签发令牌对。

| 参数 | 位置 | 类型 | 说明 |
|---|---|---|---|
| `token` | body | string | 公司统一登录令牌 |
| `uid` | body | int | 统一登录体系主键 id（`accounts.elecnest_uid` 存其字符串） |

**请求**

```json
{ "token": "eyJhbGciOiJIUzI1NiIs…", "uid": 88001 }
```

**响应 200**：`LoginResponse`（同 §1.1；`name` 取昵称，昵称为空回退用户名）

**失败**
- `400`：统一登录未启用（`ELECNEST_SSO_ENABLED=false`）
- `401`：统一登录校验失败（外部 data 为空 / 接口异常）或账号不可用

### 1.3 刷新令牌 `POST /auth/refresh`

**无需 Bearer**（凭刷新令牌本身）。换新令牌对：旧刷新令牌**原子消费作废**（Redis
GETDEL，并发重复提交也只会成功一次），返回全新访问 + 刷新令牌，两令牌 TTL 重新计满。

| 参数 | 位置 | 类型 | 说明 |
|---|---|---|---|
| `refresh_token` | body | string | 登录/上次刷新返回的刷新令牌 |

**请求**

```json
{ "refresh_token": "…" }
```

**响应 200**：`LoginResponse`（同 §1.1；全新令牌对，`name` 为 null）

**失败 401**：刷新令牌无效 / 过期 / 已被消费 → `{detail: "登录状态已失效，请重新登录"}`

> 前端策略：访问令牌剩余不足（`expires_in`）时用刷新令牌预刷新，无需用户重新登录；
> 刷新令牌本身 7 天有效期内可持续续期。

### 1.4 登出 `POST /auth/logout`

需 Bearer 认证（当前访问令牌）+ body 携带刷新令牌，一并服务端作废。

| 参数 | 位置 | 类型 | 说明 |
|---|---|---|---|
| `refresh_token` | body | string | 当前会话的刷新令牌 |

**请求**

```json
{ "refresh_token": "…" }
```

**响应 204**：空体（**幂等**——DEL 作废访问/刷新会话，key 不存在也返回 204）

**失败 401**：无 / 无效 Bearer

> 登出后本地清除两令牌即可；即使令牌被截获，刷新令牌已作废无法续期。

### 1.5 当前账号 `GET /users/me`

需认证。返回当前登录账号信息（**密码哈希不外泄**）。

**响应 200**：`AccountRecord`

| 字段 | 类型 | 说明 |
|---|---|---|
| `account_id` | string | 账号 ID（uuid 文本） |
| `name` | string | 显示名 |
| `phone` | string | 手机号 |
| `avatar` | string? | 头像（预览相对路径 `/files/{file_id}/preview`，未设置为 null） |
| `status` | "active" \| "disabled" | 账号状态 |
| `is_system` | bool | 是否超级用户 |
| `user_type` | "password" \| "elecnest" | 登录来源（统一登录为 elecnest） |
| `created_at` | string | ISO 8601 |
| `last_login_at` | string? | 最近登录时间 |

### 1.6 当前账号用量 `GET /users/me/usage`

需认证。返回当前账号累计 token 用量（按 `messages.created_by` 聚合，实时查询）。

**响应 200**：`UserUsage`

| 字段 | 类型 | 说明 |
|---|---|---|
| `account_id` | string | 账号 ID |
| `name` | string | 显示名 |
| `conversation_count` | int | 会话数（去重，含已删除） |
| `message_count` | int | 回合数 |
| `prompt_tokens` | int | 输入 token 合计 |
| `completion_tokens` | int | 输出 token 合计 |
| `total_tokens` | int | token 合计 |
| `cached_read_tokens` / `cached_write_tokens` | int | 缓存命中/写入 token |

### 1.7 每日用量 `GET /users/me/usage/daily`

需认证。返回当前账号近 `days` 天每日 token 用量（趋势图数据源，口径同 §1.6）。

| 参数 | 位置 | 类型 | 默认 | 说明 |
|---|---|---|---|---|
| `days` | query | int | 30 | 统计天数（1–90） |

**响应 200**：`DailyUsage`

```json
{
  "account_id": "3f2a9c8e-…-d1b4",
  "name": "张三",
  "days": 30,
  "items": [
    {
      "date": "2026-08-01",
      "conversation_count": 0,
      "message_count": 0,
      "prompt_tokens": 0,
      "completion_tokens": 0,
      "total_tokens": 0,
      "cached_read_tokens": 0,
      "cached_write_tokens": 0
    }
  ]
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `date` | string | 自然日（`YYYY-MM-DD`，GMT+8 墙钟） |
| 其余字段 | int | 当日聚合，口径与 §1.6 完全一致 |

`items` 规则：**每天一条、升序、零填充**（无数据日为 0）。前端图显换算：
输入未命中 = `prompt_tokens - cached_read_tokens`；输入命中 = `cached_read_tokens`；
输出 = `completion_tokens`；x 轴取 `MM-DD`。

**失败 401**：账号不存在

### 1.8 头像上传限制 `GET /users/me/avatar-config`

无需参数。返回当前头像上传限制（供前端本地校验输入；阈值全部配置驱动，前端不硬编码）。

**响应 200**：`AvatarConfig`

```json
{
  "max_size_bytes": 2097152,
  "allowed_extensions": ["png", "jpg", "jpeg", "webp", "gif"],
  "max_dimension": 512,
  "min_dimension": 32
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `max_size_bytes` | int | 体积上限（字节） |
| `allowed_extensions` | string[] | 允许的图片扩展名（不含点） |
| `max_dimension` / `min_dimension` | int | 边长上限 / 下限 |

> 头像显示目标小（≤96px 圆形），约束严于通用上传（§2.5 的 `POST /files/upload`）。

### 1.9 更新账号 `PATCH /users/me`

需认证。当前仅支持昵称（白名单字段；`phone`、`status` 等不可改）。

| 参数 | 位置 | 类型 | 说明 |
|---|---|---|---|
| `name` | body | string? | 新昵称；缺省 / `null` 保持原值 |

**请求**

```json
{ "name": "新昵称" }
```

**响应 200**：`AccountRecord`（§1.5）

**失败 400**：`{detail: "昵称不能为空"}`（`name` 提供但全空白）

### 1.10 更换头像 `POST /users/me/avatar`

需认证。请求体：`multipart/form-data`，字段名 **`file`**（`<input type="file" name="file">`）。

**响应 200**：`AccountRecord`（§1.5；`avatar` 更新为 `/files/{file_id}/preview`）

**失败 400**：
- 超过体积上限（`avatar_max_size_bytes`）
- 扩展名不在允许图片格式内
- magic bytes 与扩展名不符（伪装非图片文件）

> 服务端只做体积 / 扩展名 / magic 校验；边长区间由前端按 §1.8 本地校验。

### 1.11 修改密码 `POST /users/me/password`

需认证。

| 参数 | 位置 | 类型 | 说明 |
|---|---|---|---|
| `old_password` | body | string | 原密码（必须校验通过才允许修改） |
| `new_password` | body | string | 新密码（≥ `ACCOUNT_PASSWORD_MIN_LENGTH`，默认 8 位） |

**请求**

```json
{ "old_password": "…", "new_password": "…" }
```

**响应 200**：`AccountRecord`（§1.5）

**失败**
- `400`：新密码过短 `{detail: "新密码至少 8 位"}`；统一登录账号（`user_type=elecnest`）未设密码 `{detail: "当前账号未设置密码，无法修改"}`
- `401`：原密码错误；账号不存在

### 1.12 全量账号用量 `GET /users`（超级用户）

需认证，且当前账号 `is_system=true`；否则 `403`。返回全部账号及其用量。

**响应 200**：`UserUsage[]`（每账号一条，无消息的账号计 0）

---

## 2. 调整接口（接入认证 + 账号隔离）

### 2.1 对话 `POST /chat-messages`

**新增**：需 Bearer 认证；新建会话归属当前账号；**续聊校验归属**——用他人会话
`conversation_id` 续聊 → `404`（不泄露存在性）。

请求体不变：`{query, response_mode, conversation_id, agent_id}`。响应与 SSE 帧不变。

| 状态码 | 场景 |
|---|---|
| `200` | 正常 |
| `401` | 无/无效令牌 |
| `404` | 未知会话 / 跨账号会话 |
| `422` | `query` 为空或超长等参数校验失败 |

### 2.2 会话列表 `GET /conversations`

**新增**：需 Bearer 认证；只返回**当前账号**的会话（按 `from_account_id` 过滤）。
分页参数与响应形状不变（`ConversationRecord[]`）。

### 2.3 会话消息 `GET /conversations/{id}/messages`

**新增**：需 Bearer 认证；校验会话归属，**跨账号 → `404`**（`403` 不用于隐藏存在性）。
响应形状不变（`MessageRecord[]`）。

### 2.4 删除会话 `DELETE /conversations/{id}`

**新增**：需 Bearer 认证；校验归属，跨账号或不存在 → `404`。
成功仍为 `204` 空体。

### 2.5 文件上传 `POST /files/upload`

**新增**：需 Bearer 认证；上传文件归属当前账号（`created_by`）。
大小/扩展名限制与响应形状（`FileResponse`）不变。

---

## 3. 保持公开的接口

以下接口**无需认证**（不涉及账号数据）：

| 接口 | 说明 |
|---|---|
| `GET /files/upload` | 上传限制配置 |
| `GET /files/{file_id}/preview` | 文件预览（全局；`file_id` 为不可猜测 uuid，未做归属过滤） |
| `GET /assistants` | 助手目录（只读聚合） |

---

## 4. 数据隔离语义

| 表 | 关联列 | 语义 |
|---|---|---|
| `accounts` | `id`（uuid，`gen_random_uuid` 默认） | 登录账号；`is_system` 标注超级用户 |
| `conversations` | `from_account_id` | 会话归属账号；列表/消息/删除按此过滤 |
| `messages` | `created_by` | 回合归属；token 用量按此聚合 |
| `upload_files` | `created_by` | 文件归属（`created_by_role` 仍区分 agent/user 消费方） |
| `dedup_clues` | `created_by`（组合主键 `(created_by, clue_id)`） | 去重历史按账号隔离，互不影响 |

要点：

- 关联列存 `varchar(36)` 的 uuid 文本（`str(uuid.UUID)` 虚线形式），无外键（平台惯例）
- **跨账号不可见**：会话列表只出本人；读/删他人会话、续聊他人会话均 `404`
- **upload_files 预览保持全局**：凭 `file_id` 即可访问，不做归属过滤（用户决策）
- **dedup 按账号隔离**：`(created_by, clue_id)` 组合主键，两账号同日同产品不互相覆盖

---

## 5. 账号预置

无注册接口（用户决策）。用户由管理侧经 CLI 预置：

```bash
uv run python -m app.domain.auth.provision --phone 13800138001 --name 张三 --password '***' --superuser
```

| 参数 | 说明 |
|---|---|
| `--phone` | 登录手机号（唯一） |
| `--name` | 显示名 |
| `--password` | 明文密码（Argon2id 哈希入库，明文不落盘） |
| `--username` | 可选；唯一用户名，缺省取手机号 |
| `--superuser` | 标注超级账号（可访问 `GET /users`） |

密码存储：Argon2id PHC 自含编码（`time_cost=3 / memory_cost=65536 / parallelism=4`），
存 `accounts.password_hash`，无单独盐列。

---

## 6. 错误与状态码速查

| 状态码 | 场景 | 备注 |
|---|---|---|
| `200` | 查询/登录/刷新/更新成功 | |
| `204` | 删除/登出成功 | 空体 |
| `400` | 参数业务校验失败（头像超限/格式、昵称空白、新密码过短、统一登录未启用、elecnest 账号未设密码） | `ErrorCategory.BAD_REQUEST` |
| `401` | 未登录 / 令牌无效过期 / 刷新令牌失效 / 登录凭据错误 / 原密码错误 / 账号不存在 | `ErrorCategory.AUTH` |
| `403` | 非超级用户访问管理接口 | `ErrorCategory.DENIED` |
| `404` | 资源不存在 / 跨账号访问（不泄露存在性） | `ErrorCategory.NOT_FOUND` |
| `422` | 请求体参数校验失败 | FastAPI 默认形状 |

---

> 环境变量补充：`JWT_SECRET_KEY`（必填，≥32 字符）、`JWT_ALGORITHM`（默认 HS256）、
> `AUTH_ACCESS_TOKEN_TTL_SECONDS`（默认 86400；JWT exp 与 Redis 访问会话 TTL 对齐，Redis 为准）、
> `AUTH_REFRESH_TOKEN_TTL_SECONDS`（默认 604800）、`ACCOUNT_PASSWORD_MIN_LENGTH`（默认 8）、
> `ARGON2_TIME_COST` / `ARGON2_MEMORY_COST` / `ARGON2_PARALLELISM`。
> 认证恒启用，无开关。
