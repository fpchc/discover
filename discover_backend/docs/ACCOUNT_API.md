# 账号认证与数据隔离 API 文档

> 2026-08-28 新增。平台引入账号体系（手机号 + 密码登录，JWT 会话），并对既有
> 数据接口做**账号隔离**。此前所有接口无鉴权；本次起除特殊说明外**数据接口一律
> 需请求头 `Authorization: Bearer <JWT>`**。所有接口前缀 `/api/v1`；请求/响应
> 均为 JSON。错误统一 `{detail: <message>}`（参数校验失败为 FastAPI 默认 422 形状）。

## 目录

- [0. 认证流程与通用约定](#0-认证流程与通用约定)
- [1. 新增接口（认证）](#1-新增接口认证)
  - [1.1 登录 `POST /auth/login`](#11-登录-post-authlogin)
  - [1.2 统一登录 `POST /auth/login/elecnest`](#12-统一登录-post-authloginelecnest)
  - [1.3 当前账号 `GET /users/me`](#13-当前账号-get-usersme)
  - [1.4 当前账号用量 `GET /users/me/usage`](#14-当前账号用量-get-usersmeusage)
  - [1.5 全量账号用量 `GET /users`（超级用户）](#15-全量账号用量-get-users超级用户)
- [2. 调整接口（接入认证 + 账号隔离）](#2-调整接口接入认证--账号隔离)
  - [2.1 对话 `POST /chat-messages`](#21-对话-post-chat-messages)
  - [2.2 会话列表 `GET /conversations`](#22-会话列表-get-conversations)
  - [2.3 会话消息 `GET /conversations/{id}/messages`](#23-会话消息-get-conversationsidmessages)
  - [2.4 删除会话 `DELETE /conversations/{id}`](#24-删除会话-delete-conversationsid)
  - [2.5 文件上传 `POST /files/upload`](#25-文件上传-post-filesupload)
- [3. 保持公开的接口](#3-保持公开的接口)
- [4. 数据隔离语义](#4-数据隔离语义)
- [5. 账号预置](#5-账号预置)
- [6. 错误与状态码速查](#6-错误与状态码速查)

---

## 0. 认证流程与通用约定

1. 手机号 + 密码调 `POST /api/v1/auth/login`，成功返回 **JWT**（HS256，`sub=account_id`）
2. 后续所有受保护请求头带 `Authorization: Bearer <token>`
3. 令牌有效期默认 **7 天**（`JWT_EXPIRES_MINUTES` 配置）；无效/过期/缺失 → `401`
4. 登录失败统一 `401 手机号或密码错误`（防账号枚举）；非超级用户访问管理接口 → `403`

| 状态码 | 含义 |
|---|---|
| `401` | 未登录 / 令牌无效过期 / 账号不存在 |
| `403` | 已认证但无权限（如非 `is_system` 访问 `GET /users`） |

---

## 1. 新增接口（认证）

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
  "name": "张三"
}
```

**失败 401**：`{detail: "手机号或密码错误"}` / `{detail: "账号不可用"}`

### 1.2 统一登录 `POST /auth/login/elecnest`

公司统一登录（elecnest SSO）。开关 `ELECNEST_SSO_ENABLED=false` 时返回
`400`（未启用）。前端从公司统一登录体系拿 `token + uid` 后调本接口：后端用
`token + uid` 调统一登录用户信息接口（`ELECNEST_GET_USER_INFO_URL`，默认
`https://id.elecnest.cn/api/login/getUserInfo`）换取用户资料 → **本地注册
（find-or-create by `elecnest_uid`）** → 标记 `user_type=elecnest` → 签发 JWT。

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

### 1.3 当前账号 `GET /users/me`

需认证。返回当前登录账号信息（**密码哈希不外泄**）。

**响应 200**：`AccountRecord`

| 字段 | 类型 | 说明 |
|---|---|---|
| `account_id` | string | 账号 ID（uuid 文本） |
| `name` | string | 显示名 |
| `phone` | string | 手机号 |
| `avatar` | string? | 头像（预留） |
| `status` | "active" \| "disabled" | 账号状态 |
| `is_system` | bool | 是否超级用户 |
| `created_at` | string | ISO 8601 |
| `last_login_at` | string? | 最近登录时间 |
| `user_type` | "password" \| "elecnest" | 登录来源（统一登录为 elecnest） |

### 1.4 当前账号用量 `GET /users/me/usage`

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

### 1.5 全量账号用量 `GET /users`（超级用户）

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
uv run python -m app.services.auth_provision --phone 13800138001 --name 张三 --password '***' --superuser
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
| `200` | 查询/登录成功 | |
| `204` | 删除成功 | 空体 |
| `401` | 未登录 / 令牌无效过期 / 登录凭据错误 / 账号不存在 | `ErrorCategory.AUTH` |
| `403` | 非超级用户访问管理接口 | `ErrorCategory.DENIED` |
| `404` | 资源不存在 / 跨账号访问（不泄露存在性） | `ErrorCategory.NOT_FOUND` |
| `422` | 请求体参数校验失败 | FastAPI 默认形状 |

---

> 环境变量补充：`JWT_SECRET_KEY`（必填，≥32 字符）、`JWT_ALGORITHM`（默认 HS256）、
> `JWT_EXPIRES_MINUTES`（默认 10080）、`ARGON2_TIME_COST` / `ARGON2_MEMORY_COST` /
> `ARGON2_PARALLELISM`。认证恒启用，无开关。
