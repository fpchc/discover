# Kami 报告结构定义（V5 — Jinja2 渲染引擎）

本文档定义了客户发现报告的标准结构，对应 Jinja2 模板 `assets/eitia-cfr.html` 中的变量。

## 版本变更（V4 → V5）

- **行业全景结构化拆分**：`l0.industry_overview` HTML 块 → `l0.industry` 结构体（5 项子组件）
- **评分可追溯**：`match_subscore_N` 新增 `sub_scores`/`raw_data`/`source` 字段
- **匹配度诊断结构化**：`match_highlights`/`match_risks` 从 HTML 块改为结构化数组
- **推算公式透明**：`procurement.base_calc` 新增 `formula`/`base_source`/`coefficients` 字段
- **脉脉来源可追踪**：`contact_card` 新增 `source`/`source_confidence` 字段
- **切入策略深化**：`engagement` 新增 `positioning`/`objection_handlers` 字段
- **竞品分析深度增强**：`competition` 新增 `switching_cost`/`current_supplier_inference`/差异化对比字段
- **股权架构必填**：`equity_section` 移除 `{% if %}` 可选逻辑
- **表头修正**：`竞品/方案` → `竞品名称`
- **颜色标注规范**：新增 CSS 颜色类（置信度着色、壁垒标签、来源标注、差异化对比）

## 版本变更（V4 → V5）

---

## 一、报告骨架总览

```
封面(1页) → L0报告导读(1-2页) → L1×N 客户深度档案(N×2-3页) → 附录(2-3页)
```

| 层级 | Section | 对应 Jinja2 变量 | 填充方式 |
|------|---------|---------------|----------|
| **封面** | 产品名+副标题+公司名+元信息 | `cover.*` (7个) | AI 基于用户输入填充 |
| **L0-1** | 报告导读·30秒上手 | 硬编码框架 | 无需替换 |
| **L0-2** | 行业全景 | `l0.industry` (V5 结构体: market_size/eitia_position/customer_map/competitive_landscape/key_trends) | AI 基于搜索数据填充 |
| **L0-3** | 候选池全景 | `l0.funnel` | AI 生成（漏斗图+排除画像表） |
| **L0-4** | 信号热力图 | `l0.signal_heatmap` | AI 生成（N×5 信号矩阵表） |
| **L0-5** | TOP N 客户一览 | `l0.top_table` | AI 生成（排名表格） |
| **L1-1** | 企业速览卡 | `c.fullname/c.display_name/c.tags/...` (for 循环) | MCP 数据填充 |
| **L1-2** | 匹配度诊断 | `c.match_subscores/match_highlights/match_risks/veto_check` | AI 综合评估 |
| **L1-3** | 采购规模估算 | `c.procurement_bar/range/calc_logic/evidence_items` | AI 推断 + MCP 数据 |
| **L1-4** | 关键决策人 | `c.contacts_intro/contact_cards/decision_insight/decision_chain` | 天眼查/企查查 + 脉脉 |
| **L1-5** | 动态信号雷达 | `c.signal_cards/signal_insight` | 多源融合 |
| **L1-6** | 切入策略 | `c.pitch/talking_points/timeline/timing_badge/timing_note` | AI 生成 |
| **L1-7** | 竞品替代分析 | `c.competitor_table/substitution_path` | MCP 数据 + AI 分析 |
| **L1-8** | 风险与注意事项 | `c.risk_blocks` | 企查查风险扫描 + AI 总结 |
| **附录A** | 数据采集日志 | `appendix.data_log` | 会话自动记录 |
| **附录B** | 评分方法论 | `appendix.scoring_method` | 硬编码 |
| **附录C** | 术语解释 | `appendix.glossary` | AI 按需生成 |
| **附录D** | 免责声明 | `appendix.disclaimer` | 硬编码 |

---

## 二、封面区 `cover.*`

| Jinja2 变量 | 内容 | 来源 |
|-----------|------|------|
| `cover.title` | 报告标题（含产品名），如「高速背板连接器<br>潜在客户评估报告」 | AI 基于用户产品描述生成 |
| `cover.subtitle` | 副标题（产品定位+目标场景） | AI 生成 |
| `cover.company_name` | 委托公司名称（可选），如「XX科技有限公司」 | 用户输入（阶段 1 追问） |
| `cover.product` | 产品/服务描述，如「56G/112G PAM4 高速背板连接器」 | 用户输入 |
| `cover.scope` | 搜索范围，如「中国大陆 · 通信设备、数据中心交换机」 | 阶段 1 三层追问结果 |
| `cover.date` | 报告日期 + 数据截止日期 | 系统日期 |
| `cover.summary` | 底部摘要，如「本报告评估 5 家企业，推荐 2 家，后备 3 家」 | 评分结果 |

**HTML 关键 CSS 类**：`.cover`, `.cover-eyebrow`, `.cover-title`, `.cover-sub`, `.cover-company`, `.cover-meta`

---

## 三、L0 报告导读 `l0.*`

### L0-1：30 秒上手指引
固定框架，无需替换。

### L0-2：行业全景 `l0.industry_overview`
AI 生成。必须包含：市场规模（当前年份数据）、产业链卡位表、竞品格局表、关键洞察。

### L0-3：候选池全景

候选池的数据分为两种情况：
1. **JSON 中已有 `l0.funnel` HTML**（旧格式兼容）：模板直接 `safe` 渲染
2. **模板内置漏斗组件**（推荐）：当 JSON 没有 `l0.funnel_data` 或 `l0.funnel` 为空时，模板自动渲染通用 6 级漏斗：
   - f1: 行业企业池（全量工商登记）
   - f2: 初筛过滤（注册资金/经营状态/人员规模）
   - f3: EITIA 匹配（四层产业链卡位 + 产品关键词）
   - f4: 八维评分（8 维度加权量化）
   - f5: TOP N 推荐（综合排序精选）
   - f6: N 家完整画像（决策人/切入策略/竞品替代/风险评估）

**漏斗数字规则（V5.4.3）**：各级数字必须逐级递减，深挖数量 > 推荐数量。
- 候选池 ≥ 15 家 → 初筛 10-12 家 → 深挖 6-8 家 → 推荐 TOP 3-5 家
- 例如：18 候选 → 12 初筛 → 8 深挖 → 5 推荐（推荐数 = `l0.top_n`）
AI 生成。必须包含：漏斗图（CSS funnel 类）+ 排除画像表。

### L0-4：信号热力图 `l0.signal_heatmap`
AI 生成。N×5 矩阵表，每格用 CSS badge 标注状态。

### L0-5：TOP N 一览 `l0.top_table`
AI 生成。排列表。#/企业/地区/综合分/采购潜力/技术匹配/信用安全/一句话推荐/行动 badge。

---

## 四、L1 客户深度档案（Jinja2 `{% for c in clients %}`）

模板使用 `{% for c in clients %}` 循环渲染每客户。每客户 28 个字段，全部为 Jinja2 变量或 `| safe` HTML 块。

| Section | V5 结构化字段 |
|---------|---------|
| 1.1 企业速览卡 | `c.fullname`, `c.display_name`, `c.tags`, `c.kpi_row`, `c.oneliner`, `c.basic_table`, `c.equity_section`（**必填，≥100字符**） |
| 1.2 匹配度诊断 | `c.match_subscore_1`~`c.match_subscore_8`（8 维，各含 label/score/weight/**sub_scores/raw_data/source**），`c.match_highlights[]`（**结构化数组≥3条**），`c.match_risks[]`（**结构化数组≥2条**），`c.veto_check` |
| 1.3 采购规模估算 | `c.procurement`（scale_label/estimate_range/confidence/confidence_color/method/**base_calc{base_value/base_source/coefficients[]/formula}**/drivers[]/supplier_trend/calc_note/evidence_items[]） |
| 1.4 关键决策人 | `c.contacts_intro`, `c.contact_cards[]`（name/title/type/**source/source_confidence**/fields[]/bio），`c.decision_insight`, `c.decision_chain` |
| 1.5 动态信号雷达 | `c.signals[]`（category/level/level_label/detail/date/source），`c.signal_insight` |
| 1.6 切入策略 | `c.engagement`（**positioning**/elevator_pitch/value_props[]/entry_points[]/**objection_handlers[]**/timeline_steps[]/timing_assessment） |
| 1.7 竞品替代 | `c.competition`（competitors[]（≥3家）/**current_supplier_inference**/substitution_path/**switching_cost{financial/time/risk}**/entry_barrier{四维}/incumbent_strength/our_differentiation[]（≥3条）） |
| 1.8 风险与注意事项 | `c.risks[]`（category/level/title/detail/mitigation，≥4 条，**含risk-high**） |

---

## 五、附录 `appendix.*`

| 附录 | Jinja2 变量 | 内容 |
|------|-----------|------|
| A · 数据采集日志 | `appendix.data_log` | 表格：#/时间/目标/维度/来源类型 |
| B · 评分方法论 | `appendix.scoring_method` | 公式+权重+红线规则 |
| C · 术语解释 | `appendix.glossary` | `<dl>` 定义列表 |
| D · 免责声明 | `appendix.disclaimer` | 免责+使用建议 |
| — | `appendix.version` | 版本号 |

---

## 六、渲染管线

```
AI 采集 MCP 数据 → 生成 report_data.json
  ↓
python scripts/render_report.py report_data.json
  → JSON 验证（7 组必填字段）
  → Jinja2 渲染（StrictUndefined 模式，缺失变量报错）
  → 输出检查（残留变量 / 工具名泄漏 / 信息密度）
  → 输出完整 HTML
  ↓
cp HTML → $KAMI_DIR/templates/eitia-cfr.html
python scripts/build.py --verify eitia-cfr → PDF
```

---

## 七、追加/增量模式

追加调用（场景 C·持续跟进）时的差异：
- `cover.title` 标题加「新增客户」
- L0 导读中增加「上次推荐回顾」行
- `appendix.data_log` 标注本次为增量采集

---

## 八、工具名泄漏检查清单

`render_report.py` 自动检查，PDF 输出前必须确认：

| 禁止出现 | 替换为 |
|----------|--------|
| `tyc-mcp`、`call_tool`、`get_company_*`、`search_companies*` | 「企业公开登记信息」 |
| `qcc-mcp`、`qcc-company`、`qcc-risk`、`get_company_risk_scan`、`get_credit_evaluation` 等 | 「企业公开信用信息系统」 |
| `bocha`、`tavily`、`exa`、`tinyfish`、`anys earch` | 「行业公开搜索」 |
| `eastmoney`、`mx_*`、`tushare` | 「公开市场信息」 |
| `maimai`、`mai-mai` | 「公开职业社交平台」 |
| `playwright`、`browser_*` | 「浏览器辅助工具」 |
