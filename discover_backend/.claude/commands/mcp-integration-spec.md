# MCP 接入与能力抽象

## 适用场景 / 何时触发

- 接入 / 更换联网搜索、企业数据、财务数据等 MCP 提供方时
- 配置 MCP 注册表（`config/mcp-servers.yaml`）与 `capabilities` 能力段 / `fallback` 降级时
- 排查 MCP 调用失败、返回为空、超时时
- P2 需要接入其他 MCP 服务时的参考模板

---

## 1. 定位

平台是 MCP 的**客户端**（Streamable HTTP），不在平台内承载 MCP 服务端业务。
数据源接入遵循「**能力抽象**」：技能声明能力，注册表决定提供方
（见 `agent-package-spec.md` §4 与 `skill-assembly-spec.md` §5）。

当前接入形态（2026-09）：

| 来源 | 服务 | 用途 | 状态 |
|------|------|------|------|
| 本地自建 | `tencent_mcp` | 腾讯 WSA 联网搜索 | 启用，web_search 全部走它 |
| 本地自建 | `eastmoney_mcp` | 东方财富资讯搜索 | 启用，financial_data 备源（仅资讯，非结构化财务） |
| 远端 | `tyc_mcp` | 天眼查企业工商 | 已接真实端点，启用 |
| 占位 | `qcc_mcp` / `tushare_mcp` | 企查查 / Tushare 财务 | 未接端点，`enabled: false` |

**财务数据（financial_data）当前未接入**：tushare 占位未接、eastmoney 仅提供资讯搜索，
实际直接降级到 web_search。P2 恢复路径见 §9。

---

## 2. 传输协议

**Streamable HTTP（远程 MCP）**，不是 stdio。

理由：stdio MCP 需要在平台侧拉起子进程，而 MCP 服务运行在远端或独立本地进程，
平台只需通过 HTTP 调用。Streamable HTTP 协议是 MCP 规范为远程服务设计的变体。

传输细节：
- 基于标准 HTTP，每次调用独立请求
- 认证用 Bearer Token，从环境变量读取
- 请求体与响应体为 MCP 协议定义的 JSON 结构
- 支持流式响应（对搜索结果逐条返回，适配打字机场景）

### 2.1 本地自建 MCP 服务（tencent_mcp / eastmoney_mcp）

联网搜索与资讯类数据改为**平台本地自建 MCP 服务**。为遵循 CLAUDE.md §13.1 单一职责，
腾讯与东方财富拆为**两个独立本地 MCP 服务**，各暴露一个工具、各占一个端口与令牌，禁止混装：

- `local_mcp/tencent_mcp/`（`python -m local_mcp.tencent_mcp.main`，默认 `127.0.0.1:10001/mcp`）：
  暴露 `web_search_tencent`（腾讯 WSA SearchPro）一个工具，内部经 httpx 直连 REST。
- `local_mcp/eastmoney_mcp/`（`python -m local_mcp.eastmoney_mcp.main`，默认 `127.0.0.1:10002/mcp`）：
  暴露 `web_search_eastmoney`（东方财富 JSONP 资讯搜索）一个工具；按 IP 限流，
  `eastmoney_min_interval_seconds` 默认 1.0s。

两个服务统一收拢在 `local_mcp/` 聚合包下（`local_mcp/__init__.py` Facade），
服务边界不混装（CLAUDE.md §13.1）。

- 平台侧仍只是 MCP 客户端（`app/tools/mcp_client.py`，Streamable HTTP），一行不用改。
- 鉴权：平台分别以 `Authorization: Bearer $TENCENT_MCP_TOKEN` / `$EASTMONEY_MCP_TOKEN`
  连接，服务端校验（fail-closed）。
- 服务配置（令牌 / 端点 / 限流间隔）走 `local_mcp/tencent_mcp/settings.py` /
  `local_mcp/eastmoney_mcp/settings.py`（pydantic-settings），环境变量可覆盖；`.env.example` 见对应令牌。
- 注册表分别指向两个服务（见 §3），平台自动 `list_tools` 发现各自工具（Tier 2）。

---

## 3. 注册表配置

平台 `config/mcp-servers.yaml` 是 MCP 服务的唯一注册表。服务条目字段：

| 字段 | 说明 |
|------|------|
| `id` | 服务标识，平台内唯一，供技能清单 / 能力段引用 |
| `transport` | 传输类型，当前固定 `streamable_http` |
| `base_url` | 接入地址；支持 `${ENV_VAR:-default}` 环境变量占位 |
| `auth` | 认证方式：`type: bearer_token` + `token_env`（只存变量名） |
| `per_session` | 是否按会话独占（有状态服务 `true`，无状态共享连接 `false`） |
| `handshake_timeout_seconds` | 建连握手超时 |
| `call_timeout_seconds` | 单次调用超时 |
| `concurrency_limit` | 单服务并发上限（按上游 API 限流策略填写） |
| `enabled` | 显式开关：`false` 时装配剔除，见下 |

**认证令牌只存变量名，值从环境读取**，不写进配置文件也不写进代码。

`enabled` 显式开关：置 `false` 的条目装配时直接从能力候选 / 降级清单剔除，系统不尝试连接
该服务（占位或未启动的本地服务建议关闭，省握手超时），也不产生降级日志。**禁用 ≠ 注销**——
仍参与注册表校验（能力引用校验照常通过），只是不参与装配。占位条目（qcc/tushare）保持
`enabled: false`，接入真实端点与令牌后改 `true`。

### 3.1 capabilities 能力段

能力 = 技能与具体服务之间的抽象层。技能只声明「需要某能力」，提供方由注册表决定；
加 / 删 / 换提供方只改本注册表，不触碰智能体包内任何文件。

- `strategy: failover`：主备切换，按 `servers` 顺序优先，首个可用者生效，失败自动切换。
- `strategy: all`：全部候选各自激活为独立工具，调用哪个由模型（re-act）推理决定，
  不做切换不做降级——多搜索提供方并存时用。
- `fallback`：能力级降级。本能力全部候选不可用时，降级到 `fallback` 指向的能力
  （只允许一级降级，此处统一为 `web_search`）。降级由注册表 + 装配层 / 代理层执行，
  技能清单不写降级逻辑（见 `skill-assembly-spec.md` §5.2 / §7）。

当前能力段：

```yaml
capabilities:
  web_search:
    strategy: all           # 全部候选激活，模型（re-act）自行选调，不做主备切换
    servers:
      - tencent_mcp
  enterprise_business:       # 企业工商画像：天眼查主 / 企查查备；全不可用降级到 web_search
    strategy: failover
    servers:
      - tyc_mcp
      - qcc_mcp
    fallback: web_search
  enterprise_risk:           # 企业信用风险 / 司法 / 税务：企查查主 / 天眼查备
    strategy: failover
    servers:
      - qcc_mcp
      - tyc_mcp
    fallback: web_search
  financial_data:            # 上市财务数据：Tushare 主 / 东方财富备；当前两个候选不可用 → 直接降级 web_search
    strategy: failover
    servers:
      - tushare_mcp
      - eastmoney_mcp
    fallback: web_search
```

---

## 4. 工具清单获取

MCP 协议要求服务提供 `list_tools` 接口，返回该服务支持的全部工具及其参数约束。

平台在首次调用该服务时（或服务重启后）发起 `list_tools`，缓存结果用于构建工具目录。
**不假定工具名与参数结构**——即使是同一个提供方，不同版本的接口定义可能变化，
硬编码会在升级时失效。

预期工具可能包含（按实际 `list_tools` 结果为准）：

| 工具语义 | 典型用途 |
|---------|---------|
| 网页搜索 | 输入查询词，返回相关网页摘要 |
| 新闻搜索 | 限定时间范围的新闻检索 |
| 结构化查询 | 针对特定实体（企业、人物）的结构化信息检索 |

具体工具名、参数字段名、返回格式均以 `list_tools` 为准，代码中不出现硬编码。

---

## 5. 技能清单的依赖声明

技能不点名提供方，在 `agents/*/{skill}/SKILL.md` 的**能力依赖段**声明
（字段定义见 `agent-package-spec.md` §4.1）：

```yaml
capability_dependencies:
  - capability: web_search
    core_tools: []
    required: true
    degrade_note: null
```

**为什么核心工具列表留空**：搜索类工具的使用频率不如专有数据类工具
（企业工商 / 风险的基础查询是高频核心工具），且搜索工具名可能因服务升级变化，
列入核心工具反而增加维护成本。让模型用 `search_tools` 检索更灵活。

---

## 6. 调用流程

```
1. 技能激活
     装配层解析依赖声明 → 发现需要某能力（如 web_search）
     向 MCP 集成层请求确保该能力的候选服务可用

2. MCP 集成层
     查注册表 → 取该能力候选服务器（strategy all / failover 顺序）
     发 list_tools 请求 → 缓存工具列表
     构建工具描述符 → 标记为 Tier 2 → 并入工具目录
     （能力全部候选不可用且声明 fallback → 降级到 fallback 能力，见 skill-assembly-spec §7）

3. 模型推理
     需要搜索 → search_tools("企业风险扫描") → 找到候选工具
     describe_tool("<server>.<tool>") → 拿参数约束
     构造调用 → 工具代理分发

4. 工具代理
     识别命名空间 → 路由到 MCP 集成层
     MCP 集成层构造 Streamable HTTP 请求 → 发往服务
     流式接收响应 → 累积或逐段回传 → 应用截断策略 → 返回结果

5. 结果回模型
     成功 → 内容进上下文
     失败 → 错误分类 + 降级建议进上下文
```

---

## 7. 错误处理

| 错误类型 | 判定 | 处理 |
|---------|------|------|
| 认证失败 | HTTP 401/403 | 归类为配置错误，附"检查注册表 `token_env` 指向的环境变量"建议 |
| 请求非法 | HTTP 400 | 归类为参数错误，附参数约束说明 |
| 限流 | HTTP 429 | 归类为服务错误，附"稍后重试"建议，重试需退避 |
| 超时 | 请求超时 | 归类为超时，附"缩小查询范围"建议 |
| 服务端错误 | HTTP 5xx | 归类为服务错误，附"该数据源暂时不可用"建议，可有限重试 |
| 返回为空 | 成功但结果列表空 | 视为成功，内容为"未找到相关结果"，不是错误 |

所有错误消息必须脱敏：不含令牌、不含完整请求体。

---

## 8. 能力降级与报告质量

能力降级三级语义（注册表 `fallback` + 装配层执行，技能不写降级逻辑）：

| 级别 | 触发 | 结果 |
|------|------|------|
| 候选降级 | failover 首候选不可用 | 切下一候选，标记降级 |
| 能力降级 | 能力全部候选不可用且声明 `fallback` | 降级到 fallback 能力（如企业数据 → web_search） |
| 拒绝激活 | 必需能力全部候选不可用且无 fallback | 发错误事件并终止本轮 |

**降级后的报告质量预期**：原专有数据源（企业工商 / 风险）支撑的维度会退化为
「数据不充分·取中性分」或「基于公开信息推断」。这是接入约束下的必然权衡。

智能体侧应对：门禁放宽为「尽力采集，缺失时标注数据来源受限」；报告模板与正文
显式标注降级维度，让读者知道数据范围。

---

## 9. P2 接入其他数据源的准备

当其他 MCP 服务可用时，增量接入方式：

1. 在 `config/mcp-servers.yaml` 新增服务条目（占位条目改 `enabled: true`）
2. 搜索类通道在 `capabilities.web_search.servers` 追加提供方；专有数据源归入对应能力段，
   或在技能 SKILL.md 的 `mcp_dependencies` 新增可选依赖并附降级说明
3. 技能正文中的数据采集章节改为「优先使用专有数据源，不可用时降级」
4. 门禁逐步恢复原有要求

关键是**渐进恢复而非一步到位**：每接入一个数据源就恢复一部分维度的数据质量，
不等全部就绪才启用。

---

## 10. 自检清单

- [ ] 注册表中服务标识唯一
- [ ] 认证令牌走环境变量（`token_env`），未写进配置或代码
- [ ] 调用前执行 `list_tools`，未假定工具名
- [ ] 命名空间前缀规则一致（服务标识 + 点号）
- [ ] 能力段 strategy / fallback 语义正确，未出现二级以上 fallback
- [ ] 占位条目保持 `enabled: false`
- [ ] 错误消息已脱敏
- [ ] 返回为空视为成功而非错误
- [ ] 数据受限场景的门禁已放宽，报告已标注降级维度
