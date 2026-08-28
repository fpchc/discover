# 客户账期评估 — 数据源映射

> 本文件定义每个数据点 → 主源 MCP → 验证源 MCP 的精确映射。AI 采集时按此表调用，不做模糊搜索。

---

## 一、MCP 数据源分配

| MCP 数据源 | 承担的采集维度 | 具体字段 |
|---|---|---|
| **天眼查 tyc-mcp** | 工商画像/股权/人员/风险 | 实体锚定、注册资本、参保、实控人、股东、决策人、司法风险概览 |
| **企查查 qcc-mcp（6 Server）** | 工商/风险/知识产权/经营 | registration_info、risk_scan、tax_arrears、default_info、annual_reports、equity_freeze/pledge、administrative_penalty |
| **东方财富 mx-ds-mcp** | 行情/财务/新闻/研报 | 营收/净利/毛利率、主营构成、前五大供应商、研报、公告 |
| **Tushare tushareMcp** | 财务指标时序/审计 | fina_indicator、cashflow、income、balancesheet、fina_audit、stock_basic |
| **博查 bocha-search-mcp** | 中文舆情/行业动态 | PCB 占比基准、支付习惯、拖欠货款报道 |
| **Tavily tavily-remote-mcp** | 搜索+网页提取/交叉验证 | 年报原文提取、双源校验 |
| **Exa exa** | 英文语义搜索/海外对标 | 海外客户、品牌声誉、行业基准 |
| **AnySearch anysearch** | 垂直搜索/批量提取 | 行业报告、BOM 成本结构研究 |
| **TinyFish tinyfish** | 轻量搜索+网页获取 | 官网采集、行业网站浏览 |

**纪律**：所有已装 MCP 必须全部参与采集，不得只依赖天眼查/企查查——每个 MCP 至少承担一个数据维度。

---

## 二、数据点 → 工具精确映射

### 2.1 工商基础（P0 双源）

| 数据点 | 主源工具 | 验证源工具 |
|--------|----------|-----------|
| 实体锚定 | 天眼查 `search_companies` | —（唯一入口）|
| 注册资本/实缴 | 天眼查 `get_company_basic_profile` | 企查查 `get_company_registration_info` |
| 统一社会信用代码 | 同上 | 同上 |
| 法定代表人 | 同上 | 同上 |
| 成立日期 | 同上 | 同上 |
| 参保人数 | 天眼查 | 企查查 `get_annual_reports` |
| 经营状态 | 天眼查 `get_company_basic_profile` | — |

### 2.2 财务数据（上市客户，P1 双源）

| 数据点 | 主源工具 | 验证源工具 |
|--------|----------|-----------|
| 营收/净利/毛利率 | 东方财富 `mx_ashare_finance_data` | Tushare `fina_indicator` |
| 负债率/流动比 | Tushare `fina_indicator` | 东方财富 |
| 应收/存货/总资产周转 | Tushare `fina_indicator` | 东方财富 |
| 经营现金流 | Tushare `cashflow` | 东方财富 |
| 审计意见 | Tushare `fina_audit` | 年报原文（Tavily/AnySearch 提取）|
| 上市状态/代码 | 天眼查 `search_listed_companies` | Tushare `stock_basic` |

### 2.3 风险数据（P0/P1 双源）

| 数据点 | 主源工具 | 验证源工具 |
|--------|----------|-----------|
| 失信/被执行/限高 | 企查查 `get_company_risk_scan` / `get_dishonest_info` | 天眼查司法维度 |
| 欠税/税务违法 | 企查查 `get_tax_arrears_notice` / `get_tax_violation` | 天眼查 |
| 票据违约 | 企查查 `get_default_info` | 博查/Tavily 搜索 |
| 经营异常 | 企查查 `get_business_exception` | 天眼查 |
| 股权冻结/出质 | 企查查 `get_equity_freeze` / `get_equity_pledge_info` | 天眼查 |
| 行政处罚 | 企查查 `get_administrative_penalty` | 天眼查 |
| 裁判文书 | 企查查 `get_judicial_documents` | 天眼查司法维度 |

### 2.4 需求盘子与舆情

| 数据点 | 主源工具 | 验证源工具 |
|--------|----------|-----------|
| 主营构成 | 东方财富 `mx_finance_search_news` + 年报 | 年报原文 |
| 前五供应商采购额 | 东方财富 `mx_finance_search_news` + 年报 | 年报原文（Tavily/AnySearch）|
| 招股书原材料构成 | Tavily/TinyFish 提取 PDF | 年报 |
| 决策人/联系方式 | 天眼查 `get_company_people` | 企查查 `get_key_personnel` |
| 新闻舆情 | 博查 `bocha_web_search` | Exa/AnySearch/TinyFish |
| 海外客户/声誉 | Exa `web_search_exa` | 博查/Tavily 中文交叉 |

---

## 三、实体锚定铁律

企业查询**必须先过天眼查 `search_companies` 完成实体锚定**，再用企查查深度查询。企查查调用必须使用**完整企业登记名**（18 位信用代码或完整名称），禁止简称。

- 完整名：满足 18 项组织后缀白名单（有限公司/股份有限公司/集团等）→ 直接查询
- 简称/品牌名/股票简称 → 必须先 `get_company_by_query` 消歧，多候选时由用户选择

---

## 四、采集批次策略

**并发批次一次发所有工具调用**，不逐批追加。同一批内：

1. 天眼查 `search_companies`（实体锚定）
2. 天眼查 `get_company_basic_profile` + 企查查 `get_company_registration_info`（P0 工商双源）
3. 企查查 `get_company_risk_scan`（35 因子全量）
4. Tushare `fina_indicator` + `cashflow` + `fina_audit`（上市财务）
5. 东方财富 `mx_ashare_finance_data`（财务双源）
6. 企查查风险明细（dishonest/tax_arrears/default_info/business_exception/equity_freeze/administrative_penalty）
7. 搜索类（博查/Exa/AnySearch/TinyFish）——舆情 + 需求盘子基准

---

> **注意**：实际可用 MCP 以当前环境的 tools/list 为准，映射表所列工具名若当前未授权，按能力降级处理，不得编造。
