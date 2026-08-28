# 客户发现报告结构定义

— Jinja2 渲染引擎

本文档定义客户发现报告的标准结构，对应模板 `templates/cfr.html` 中的变量。

## 版本变更（V4 → V5）

- **行业全景结构化拆分**：`l0.industry_overview` HTML 块 → `l0.industry` 结构体（5 项子组件）
- **评分可追溯**：`match_subscore_N` 新增 `sub_scores`/`raw_data`/`source` 字段
- **匹配度诊断结构化**：`match_highlights`/`match_risks` 从 HTML 块改为结构化数组
- **推算公式透明**：`procurement.base_calc` 新增 `formula`/`base_source`/`coefficients` 字段
- **决策人来源可追踪**：`contact_card` 新增 `source`/`source_confidence` 字段
- **切入策略深化**：`engagement` 新增 `positioning`/`objection_handlers` 字段
- **竞品分析深度增强**：`competition` 新增 `switching_cost`/`current_supplier_inference`/差异化对比字段
- **股权架构必填**：`equity_section` 移除 `{% if %}` 可选逻辑
- **颜色标注规范**：新增 CSS 颜色类（置信度着色、壁垒标签、来源标注、差异化对比）

## 一、报告骨架总览

```
封面(1页) → L0报告导读(1-2页) → L1×N 客户深度档案(N×2-3页) → 附录(2-3页)
```

| 层级 | Section | 对应 Jinja2 变量 | 填充方式 |
|------|---------|---------------|----------|
| **封面** | 产品名+副标题+公司名+元信息 | `cover.*` (8个) | AI 基于用户输入填充 |
| **L0-1** | 报告导读·30秒上手 | 硬编码框架 | 无需替换 |
| **L0-2** | 行业全景 | `l0.industry`（V5 结构体） | AI 基于搜索数据填充 |
| **L0-3** | 候选池全景 | `l0.funnel` | AI 生成（漏斗图+排除画像表） |
| **L0-4** | 信号热力图 | `l0.signal_heatmap` | AI 生成（N×5 信号矩阵表） |
| **L0-5** | TOP N 客户一览 | `l0.top_table` | AI 生成（排名表格） |
| **L1-1** | 企业速览卡 | `c.fullname/c.display_name/c.tags/...` | 搜索数据填充 |
| **L1-2** | 匹配度诊断 | `c.match_subscores/match_highlights/match_risks/veto_check` | AI 综合评估 |
| **L1-3** | 采购规模估算 | `c.procurement_*` | AI 推断 + 搜索数据 |
| **L1-4** | 关键决策人 | `c.contacts_intro/contact_cards/decision_insight/decision_chain` | 搜索 + 工商公开信息 |
| **L1-5** | 动态信号雷达 | `c.signal_cards/signal_insight` | 多源融合 |
| **L1-6** | 切入策略 | `c.pitch/talking_points/timeline/timing_badge/timing_note` | AI 生成 |
| **L1-7** | 竞品替代分析 | `c.competitor_table/substitution_path` | 搜索数据 + AI 分析 |
| **L1-8** | 风险与注意事项 | `c.risk_blocks` | 搜索风险信息 + AI 总结 |
| **附录A** | 数据采集日志 | `appendix.data_log` | 会话自动记录 |
| **附录B** | 评分方法论 | `appendix.scoring_method` | 硬编码 |
| **附录C** | 术语解释 | `appendix.glossary` | AI 按需生成 |
| **附录D** | 免责声明 | `appendix.disclaimer` | 硬编码 |

## 二、封面区 `cover.*`

| Jinja2 变量 | 内容 | 来源 |
|-----------|------|------|
| `cover.title` | 报告标题（含产品名） | AI 基于用户产品描述生成 |
| `cover.subtitle` | 副标题（产品定位+目标场景） | AI 生成 |
| `cover.company_name` | 委托公司名称（可选） | 用户输入（阶段 1 追问） |
| `cover.product` | 产品/服务描述 | 用户输入 |
| `cover.scope` | 搜索范围 | 阶段 1 三层追问结果 |
| `cover.date` | 报告日期 | 系统日期 |
| `cover.data_date` | 数据截止日期 | 系统日期 |
| `cover.summary` | 底部摘要 | 评分结果 |

**P1 标注**：`cover.summary` 首句须注明「数据来源受限版本：公开搜索」，让读者明确数据范围。

## 三、L0 报告导读 `l0.*`

### L0-2：行业全景 `l0.industry`（V5 结构体）

AI 生成，必须包含 5 项子组件：

| 子组件 | 类型 | P1 最低要求 |
|--------|------|-----------|
| `market_size` | 结构体 {amount, unit, yoy_growth, year, source, sub_segments} | 含年份数字；数据不足标注「估算」 |
| `position` | 多层结构体（my_tier/upstream_layers/downstream_direct） | 至少 my_tier + 直接下游 |
| `customer_map` | 数组 ≥ 1 | 每个含 description |
| `competitive_landscape` | 数组 ≥ 1 | — |
| `key_trends` | 数组 ≥ 1 | 每个含 trend + driver |

### L0-3：候选池全景 `l0.funnel` / `l0.funnel_data`

`l0.funnel` 可放 HTML；模板若检测到 `l0.funnel_data`（数组）则渲染内置漏斗组件，每项 `{level, label, detail}`。**漏斗数字规则**：候选池 > 初筛 > 深挖 > 推荐（各级至少差 1）。P1 候选池 ≥ 5 家即可（迁移规范 §5 放宽）。

### L0-4：信号热力图 `l0.signal_heatmap`；L0-5：TOP N 一览 `l0.top_table`

AI 生成，格式沿用 V5。

## 四、L1 客户深度档案（Jinja2 `{% for c in clients %}`）

模板用 `{% for c in clients %}` 循环渲染每客户。每客户 30 个字段（16 个顶层 + 14 个结构化子字段），全部为 Jinja2 变量或 `| safe` HTML 块。

| Section | V5 结构化字段 |
|---------|---------|
| 1.1 企业速览卡 | `c.fullname`, `c.display_name`, `c.score`, `c.rank`, `c.tags`, `c.kpi_row`, `c.oneliner`, `c.basic_table`, `c.equity_section` |
| 1.2 匹配度诊断 | `c.match_subscore_1`~`c.match_subscore_8`（各含 label/score/weight/sub_scores/raw_data/source），`c.match_highlights[]`, `c.match_risks[]`, `c.veto_check` |
| 1.3 采购规模估算 | `c.procurement`（scale_label/estimate_range/confidence/confidence_color/method/base_calc{base_value/base_source/coefficients[]/formula}/drivers[]/supplier_trend/calc_note/evidence_items[]） |
| 1.4 关键决策人 | `c.contacts_intro`, `c.contact_cards[]`（name/title/type/source/source_confidence/fields[]/bio）, `c.decision_insight`, `c.decision_chain` |
| 1.5 动态信号雷达 | `c.signals[]`（category/level/level_label/detail/date/source）, `c.signal_insight` |
| 1.6 切入策略 | `c.engagement`（positioning/elevator_pitch/value_props[]/entry_points[]/objection_handlers[]/timeline_steps[]/timing_assessment） |
| 1.7 竞品替代 | `c.competition`（competitors[]/current_supplier_inference/substitution_path/switching_cost/entry_barrier/incumbent_strength/our_differentiation[]） |
| 1.8 风险与注意事项 | `c.risks[]`（category/level/title/detail/mitigation） |

## 四·五、JSON 结构规范（以模板为准）

**权威 schema 在 `schemas/report_schema.json`**（单一事实来源，字段齐全检查据此生成）。`render_report` 渲染采用容错环境（缺失字段渲染为空，不报错），字段齐全度由 `check_completeness` 以警告列出。以下列出模板实际循环的结构形状（字段名与模板一致）：

| 字段 | 结构形状 | 备注 |
|------|---------|------|
| `l0.industry.market_size` | `{amount, unit, yoy_growth, year, source, sub_segments:[{name, share, trend}]}` | `sub_segments` 每项须含 `name`/`share`/`trend`（mini-bar 渲染） |
| `l0.industry.position` | `{my_tier, my_subcategory, upstream_layers:[{tier, category, products, company_examples:[...]}], downstream_direct:[...], downstream_indirect:[...]}` | 各 layer 按 `tier` 排序；`company_examples` 为示例企业数组（可为空） |
| `l0.industry.customer_map` | `[{sub_industry, description, potential, reason}]` | — |
| `l0.industry.competitive_landscape` | `[{competitor, share, note}]` | — |
| `l0.industry.key_trends` | `[{trend, driver, timeline}]` | — |
| `clients[].match_highlights` | `[{dim, fact, value, icon}]` | — |
| `clients[].match_risks` | `[{dim, issue, impact}]` | — |
| `clients[].procurement.base_calc.coefficients` | `[{name, value, reason}]` | — |
| `clients[].procurement.evidence_items` | `[{body, source}]` | — |
| `clients[].contact_cards[]` | `{name, title, type, source, source_confidence, fields:[{label,value}], bio, gov_role}` | 工商来源卡片 `gov_role` 尽量填董监高角色（如「董事」） |
| `clients[].signals[]` | `{category, level, level_label, detail, date, source, metrics:{...}}` | `metrics` 须存在（可为空对象） |
| `clients[].engagement.value_props` | `[{prop, mapping}]` | — |
| `clients[].engagement.entry_points` | `[{hook, context, trend}]` | — |
| `clients[].engagement.objection_handlers` | `[{objection, response}]` | — |
| `clients[].engagement.timeline_steps` | `[{phase, action, week}]` | — |
| `clients[].engagement.timing_assessment` | `{badge, note}` | — |
| `clients[].competition.competitors` | `[{name, market_share, core_strength, core_weakness, customer_profile, our_advantage}]` | — |
| `clients[].competition.substitution_path` | `{type, success_rate, timeline, summary, total_timeline, key_risk, steps:[{phase, action, duration, barrier, owner}]}` | `summary`/`total_timeline`/`key_risk` 必填；steps 与 type 分支模板都渲染 |
| `clients[].competition.switching_cost` | `{financial, time, risk}` 各为 `{value, label, sub_items:[{name, cost, note}]}` | `sub_items` 每项含 `name` |
| `clients[].competition.our_differentiation` | `[{dim, them, us, advantage}]` | — |
| `clients[].risks[]` | `{category, level, title, detail, mitigation}` | — |

**P1 提示**：数据受限时上述字段可填「推断」/「数据不充分·取中性分」。模板容错渲染，缺失字段渲染为空；字段齐全度会以警告列出，请尽量按结构形状完整填充。

## 五、附录 `appendix.*`

| 附录 | Jinja2 变量 | 内容 |
|------|-----------|------|
| A · 数据采集日志 | `appendix.data_log` | 表格：#/时间/目标/维度/来源类型 |
| B · 评分方法论 | `appendix.scoring_method` | 公式+权重+红线规则 |
| C · 术语解释 | `appendix.glossary` | `<dl>` 定义列表 |
| D · 免责声明 | `appendix.disclaimer` | 免责+使用建议 |
| — | `appendix.version` | 版本号 |

**P1 标注**：附录 A 每条日志的「来源类型」须突出实际使用的搜索工具（`web_search` 系列），让读者明确数据范围。

## 六、渲染管线（P1）

```
AI 采集搜索数据 → 按本结构组织报告 JSON
  ↓
调用 render_report（入参 data 内联传报告本体，禁止传文件路径）
  → 结构校验（阻断级，clients 非空数组）+ 字段齐全/数据完整性警告
  → Jinja2 渲染（容错）+ 输出检查（无残留变量/无工具名泄漏/无 CSS 泄露）
  → 报告 JSON 落盘工作区 output/report.json，HTML 输出到工作区 output/，自动登记为可下载产物
  ↓
调用 gate_render_pass（入参 report_json: "output/report.json"）做阻断级结构校验
```

**入参约束**：AI 无写文件工具，报告 JSON 只能经 `render_report` 的 `data` 字段内联到达脚本；脚本渲染时把数据落盘 `output/report.json`，门禁 `gate_render_pass` 据此引用。

**P1 与旧版差异**：不再依赖外部 Kami 部署与 PDF 构建；报告在脚本容器内直接渲染 HTML，作为可下载产物交付。PDF 属 P2。

## 七、追加/增量模式

追加调用（场景 C·持续跟进）时的差异：
- `cover.title` 标题加「新增客户」
- L0 导读中增加「上次推荐回顾」行
- `appendix.data_log` 标注本次为增量采集

## 八、工具名泄漏检查清单

`render_report.py` 自动检查，输出前必须确认：

| 禁止出现 | 替换为 |
|----------|--------|
| `tyc-mcp`、`call_tool`、`get_company_*`、`search_companies*` | 「企业公开登记信息」 |
| `qcc-mcp`、`qcc-company`、`qcc-risk`、`get_company_risk_scan`、`get_credit_evaluation` 等 | 「企业公开信用信息系统」 |
| `bocha`、`tavily`、`exa`、`tinyfish`、`anysearch` | 「行业公开搜索」 |
| `eastmoney`、`mx_*`、`tushare` | 「公开市场信息」 |
| `maimai`、`mai-mai` | 「公开职业社交平台」 |
| `playwright`、`browser_*` | 「浏览器辅助工具」 |
| 脚本名/模板名（`score_calculator.py` 等） | 不上屏 |

**P1 放宽说明**：以上为渲染输出中的泄漏检查（警告级）。实际生效的搜索工具限定名（如 `alibaba_search.web_search` / `yuanbao_search.web_search`）允许出现在附录 A 数据日志中，因为那就是本次真实数据范围，需如实披露。
