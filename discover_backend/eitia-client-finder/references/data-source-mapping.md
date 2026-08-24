# 数据源调用映射表

本文档定义客户发现报告 15 个板块与 MCP/Skill 工具的精确映射关系，包括工具名称、调用方式、关键参数、降级策略和并发依赖关系。

> **数据源策略**：天眼查 (tyc-mcp) + 企查查 (qcc-mcp) **双源互补**。天眼查广度优先（88工具，集团/供应链/搜索），企查查深度优先（信用评价4维/新闻情感分类/联系方式丰富度）。妙想 (mx-ds-mcp) = 上市公司财务，博查/Tavily/AnySearch/Exa = 搜索与动态。

---

## 附录：天眼查 vs 企查查 能力分工矩阵

> 基于中兴通讯实测对比。**42%天眼查独有** + **25%企查查更强** + **33%共有互为备选**。

| 维度 | 首选工具 | 理由 | 备选 |
|------|:--:|------|:--:|
| ① 工商+标签+Logo | **天眼查** `tyc-mcp: get_company_basic_profile` | 含标签/Logo/园区/企业简介/规模，信息更完整 | 企查查 |
| ① 联系方式(电话/邮箱/网址) | **企查查** `qcc-company: get_contact_info` | 8电话+9邮箱+5网址 vs 天眼查2+2+1 | 天眼查 |
| ① 股东 | 天眼查/企查查均可 | 两者数据一致 | — |
| ② 产品/技术 | 天眼查 `get_products_info` + 企查查 `get_patent_info` + TinyFish官网 | 天眼查有产品维度，企查查有专利，互补 | Tavily |
| ③ 供应商/客户 | **天眼查** `call_tool → get_suppliers_and_customers` | 80供应商+887客户含金额，**企查查无此能力** | Tavily研报 |
| ③ 对外投资 | 天眼查/企查查均可 | 数据一致 | — |
| ④ 高管(含薪酬+履历) | **天眼查** `get_company_people` | 含年薪(徐子阳738万)+持股+核心团队20人，企查查无 | 企查查 `get_key_personnel` |
| ⑥ 风险35因子扫描 | **企查查** `qcc-risk: get_company_risk_scan` | 一键35因子，比天眼查 `get_risk_overview` 更结构化 | 天眼查 |
| ⑥ 信用评价 | **企查查** `qcc-operation: get_credit_evaluation` | 4维(纳税A级12年+债券AAA+海关高级+行业AAA) | 天眼查 |
| ⑧ 集团穿透 | **天眼查** `get_company_group_profile` | 215成员+实控人+上市公司数，**企查查无此能力** | 企查查投资 |
| ⑨ 新闻情感 | **企查查** `qcc-operation: get_news_sentiment` | 附积极/中立/消极分类，天眼查新闻无分类 | 博查 |
| ⑨ 招聘 | 天眼查 `call_tool → get_recruitment_info` + 企查查 | 双源互补：天眼查含链接，企查查含薪资 | 博查 |
| ⑨ 招投标 | 企查查/天眼查均可 | 数据量均大，互为备选 | AnySearch |
| ⑨ 财务 | **妙想** `mx-ds-mcp: mx_ashare_finance_data` | 已确认最优，覆盖营收/利润/毛利率/PE/PB/研发 | 天眼查 `get_financial_summary` |
| 🆕 关系图谱 | **天眼查** `get_relation_graph` + `get_relation_path` | **企查查无此能力** | 企查查投资+股东 |
| 🆕 融资 | **天眼查** `get_financing_records` | **企查查无此能力** | Tavily |
| 🔍 企业搜索 | **天眼查** `search_companies` + `search_companies_by_industry_region` | **企查查无批量搜索能力** | 博查关键词 |
| 📜 专利 | 天眼查 `get_patent_info` + 企查查 `qcc-ipr: get_patent_info` | 两者数据量相当，互为备选 | — |

---

## 一数据源速查总表

| 板块编号 | 板块名称 | 主力工具（已验证） | 备选/降级 | 弃用 |
|---------|---------|:--:|------|:--:|
| ① | 公司基本信息 | **天眼查** `tyc: get_company_basic_profile` ⭐⭐⭐ (含标签/Logo/简介) + **企查查** `qcc-company: get_contact_info` ⭐⭐⭐ (电话/邮箱更全) | 东方财富（上市公司） | — |
| ② | 产品/技术匹配 | TinyFish/Tavily 官网提取 ⭐⭐⭐ + **天眼查** `tyc: get_products_info` ⭐⭐ + **企查查** `qcc-ipr: get_patent_info` ⭐⭐⭐ | — | — |
| ③ | 采购潜力 | **天眼查** `tyc: call_tool → get_suppliers_and_customers` ⭐⭐⭐ (独有！80供应商+887客户) + Tavily 研报 ⭐⭐⭐ | 企查查投资 + 东方财富 | — |
| ④ | 关键决策人 | **天眼查** `tyc: get_company_people` ⭐⭐⭐ (含薪酬+持股+履历+核心团队) + **企查查** `qcc-company: get_contact_info` ⭐⭐⭐ + **脉脉 `maimai-prospect`（V5 硬约束·不可跳过）⭐⭐⭐** 于深挖第一批工具调用中并发 | Exa `category:people` ⭐⭐ | — |
| ⑤ | 触达策略 | AI 综合生成 | — | — |
| ⑥ | 风险评估 | **企查查** `qcc-risk: get_company_risk_scan` ⭐⭐⭐ (35因子) + `qcc-operation: get_credit_evaluation` ⭐⭐⭐ (4维信用) + **天眼查** `tyc: get_risk_overview` ⭐⭐ (备选) | 东方财富 | — |
| ⑦ | 客户对比总览 | AI 汇总评分数据 | — | — |
| ⑧ | 产业链定位 | **天眼查** `tyc: get_company_group_profile` ⭐⭐⭐ (独有！215成员+实控人) + AI EITIA 四层规则 | 企查查投资 + 博查 | — |
| ⑨ | 动态信号 | **博查新闻 ⭐⭐⭐** + **企查查** `qcc-operation: get_news_sentiment` ⭐⭐⭐ (附情感分类) + **天眼查** `tyc: get_news_sentiment` ⭐⭐ (备选) | Tavily ⭐⭐⭐ + 东方财富 ⭐⭐ | — |
| ⑨ | 招聘信号 | **天眼查** `tyc: call_tool → get_recruitment_info` ⭐⭐⭐ (含链接) + **企查查** `qcc-operation: get_recruitment_info` ⭐⭐⭐ (含薪资) | 博查 ⭐⭐⭐ | — |
| ⑨ | 招投标信号 | **企查查** `qcc-operation: get_bidding_info` ⭐⭐⭐ + **天眼查** `tyc: get_bidding_info` ⭐⭐⭐ (双源互补) + **AnySearch ⭐⭐⭐** | 博查 | — |
| ⑨ | 财务数据 | **东方财富** `mx-ds-mcp: mx_ashare_finance_data` ⭐⭐⭐ + **天眼查** `tyc: get_financial_summary` ⭐⭐ (备选) | Tushare `stock_basic` ⭐⭐ | — |
| ⑩ | 切入机会点 | AI 综合生成 | — | — |
| ⑫ | 竞品渗透 | **Tavily 研报 ⭐⭐⭐** + 博查 ⭐⭐ + Exa ⭐⭐ | — | 天眼查 `get_competitors` ❌ |
| 🆕 | 客户痛点 | AI 综合推断 | — | — |
| 🆕 | 采购时机 | AI 整合 + 时间衰减计算 | — | — |
| 🆕 | 追客矩阵 | AI 生成 | — | — |
| 🆕 | 关系网络 | **天眼查** `tyc: get_relation_graph` ⭐⭐⭐ + `get_relation_path` ⭐⭐⭐ (独有！) + **脉脉（必选）⭐⭐⭐** | 企查查投资+股东 + Exa LinkedIn | — |
| 🆕 | 行业展会 | **AnySearch ⭐⭐⭐ + 博查 ⭐⭐⭐** | Tavily | — |
| 🆕 | 专利技术 | **天眼查** `tyc: get_patent_info` + **企查查** `qcc-ipr: get_patent_info` (双源互补) | — | — |
| 🆕 | 融资历史 | **天眼查** `tyc: get_financing_records` ⭐⭐⭐ (独有！) | — | — |

---

## 二企业搜索与发现（阶段 2.1）

### 通道 1：行业+区域批量搜索

**主力工具**：**天眼查** `search_companies_by_industry_region`（企查查无此能力）

| 参数 | 说明 | 示例 |
|------|------|------|
| `industry` | 行业关键词 | "通信设备" / "电子元器件" |
| `region` | 省/市名称 | "广东" / "苏州" |
| `page` | 页码 | 1 |
| `page_size` | 每页条数 | 20 |

**降级**：天眼查不可用 → 博查 `"{行业} {区域} 企业 排名 2026"` + Tavily

### 通道 2：企业精确搜索/锚定

**主力工具**：**天眼查** `search_companies`（企查查无此能力，但企查查要求输入完整企业名）

| 参数 | 说明 | 示例 |
|------|------|------|
| `searchKey` | 企业名称关键词 | "中兴通讯" / "锐捷网络" |

**降级**：天眼查不可用 → 博查关键词搜索 → 确认完整企业名后直接用企查查查询

### 通道 3：竞品客户逆向发现

**主力工具**：博查 `bocha_web_search` + Tavily `tavily_search`

**搜索模式**：`"{竞品名} 客户" / "{竞品名} 供应链" / "{竞品名} 供应商"`

### 通道 4：招投标反向发现客户

**主力工具**：AnySearch `search`

**搜索模式**：`"{产品品类} 招标 采购" / "{产品品类} 采购公告"`

### 通道 5：海外客户补充

**主力工具**：Exa `web_search_exa`

**搜索模式**：英文关键词（如 `"high speed backplane connector" buyer`）

### 通道 6：上市公司筛选

**主力工具**：东方财富 `mx-ds-mcp: mx_stocks_screener`

---

## 三企业深挖（阶段 2.3）—— 逐维度映射

### ① 公司基本信息

| 步骤 | 工具 | 关键参数 |
|------|------|----------|
| 主调用 | **天眼查** `tyc: get_company_basic_profile` | `company_name: "企业全称"` |
| 联系方式 | **企查查** `qcc-company: get_contact_info` | `searchKey: "企业全称"` |
| 股东信息 | **天眼查** `tyc: call_tool → get_shareholder_info` 或企查查 | `page:1, page_size:20` |
| 实控人 | **企查查** `qcc-company: get_actual_controller` | `searchKey: "企业全称"` |
| 上市公司补充 | 东方财富 `mx-ds-mcp: mx_ashare_finance_data` | 自然语言："XX公司 基本信息 估值" |

**降级**：天眼查不可用 → 企查查 `get_company_registration_info` → 博查整理

### ② 产品/技术匹配

| 步骤 | 工具 | 关键参数 |
|------|------|----------|
| 1. 官网提取 | TinyFish `fetch_content` | `url: "企业官网URL"` |
| 2. 官网提取降级 | Tavily `tavily_extract` | `urls: ["官网URL"]`, `extract_depth: "advanced"` |
| 3. 产品信息 | **天眼查** `tyc: get_products_info` | `company_name: "企业全称"` |
| 4. 专利技术 | **企查查** `qcc-ipr: get_patent_info` + **天眼查** `tyc: get_patent_info` | `searchKey: "企业全称"` |
| 5. 研报补充 | Tavily `tavily_search` | `query: "{企业名} 产品 技术参数"` |

### ③ 采购潜力

| 步骤 | 工具 | 关键参数 |
|------|------|----------|
| 1. **供应商/客户** | **天眼查** `tyc: call_tool → get_suppliers_and_customers` | `arguments: {page:1, page_size:10}` |
| 2. 对外投资 | 天眼查/企查查均可 | `searchKey: "企业全称"` |
| 3. 研报深度 | Tavily `tavily_search` | `query: "{企业名} 供应链 采购"` |
| 4. 上市公司补充 | 东方财富 | 营收结构推断采购量 |

> **天眼查 `get_suppliers_and_customers` 为独有能力**，企查查无替代。若天眼查不可用，此维度严重受限。

### ④ 关键决策人

| 步骤 | 工具 | 关键参数 |
|------|------|----------|
| 1. 董监高+薪酬+履历 | **天眼查** `tyc: get_company_people` | `company_name: "企业全称"` |
| 2. 联系方式 | **企查查** `qcc-company: get_contact_info` | `searchKey: "企业全称"` |
| 3. **脉脉人脉（必选）** | Skill `maimai-prospect` | 采用其标准调用流程 |
| 4. 海外管理层补充 | Exa `web_search_exa` | `query: "{英文公司名} procurement"` |

**降级**：天眼查不可用 → 企查查 `get_key_personnel`（缺薪酬/持股/核心团队）→ 脉脉补足

### ⑥ 风险评估

| 步骤 | 工具 | 关键参数 |
|------|------|----------|
| 1. 风险总览(35因子) | **企查查** `qcc-risk: get_company_risk_scan` | `searchKey: "企业全称"` |
| 2. 信用评价(4维) | **企查查** `qcc-operation: get_credit_evaluation` | `searchKey: "企业全称"` |
| 3. 风险备选 | **天眼查** `tyc: get_risk_overview` | `company_name: "企业全称"` |
| 4. 上市公司财务风险 | 东方财富 | ST/亏损/异常检查 |

### ⑧ 产业链定位

| 步骤 | 工具 | 关键参数 |
|------|------|----------|
| 1. **集团穿透** | **天眼查** `tyc: get_company_group_profile` | `company_name: "企业全称"` |
| 2. 对外投资 | 天眼查/企查查均可 | `searchKey: "企业全称"` |
| 3. EITIA 层级推断 | AI 规则引擎 | 基于 `references/eitia-architecture.md` |

> **天眼查 `get_company_group_profile` 为独有能力**（215成员+实控人+上市公司数），企查查无替代。

### ⑨ 动态信号

| 维度 | 主力工具 | 调用方式 | 备选 |
|------|----------|----------|------|
| 新闻动态 | **博查** ⭐⭐⭐ | `query: "{企业名}"`, `freshness: "oneMonth"` | Tavily |
| 新闻情感 | **企查查** `qcc-operation: get_news_sentiment` ⭐⭐⭐ | `searchKey: "企业全称"`，附情感分类 | 天眼查 |
| 招聘 | **天眼查** `tyc: call_tool → get_recruitment_info` + **企查查** | 双源互补 | 博查 |
| 招投标 | **企查查** `qcc-operation: get_bidding_info` + **天眼查** `tyc: get_bidding_info` | 双源互补 | AnySearch(全局) |
| 财务 | **东方财富** `mx-ds-mcp: mx_ashare_finance_data` ⭐⭐⭐ | 自然语言即可 | 天眼查 `get_financial_summary` |
| 融资 | **天眼查** `tyc: get_financing_records` | `company_name: "企业全称"` | Tavily |
| 行业展会 | AnySearch + 博查 | `query: "{行业} 展会 2026"` | Tavily |

### ⑫ 竞品渗透

| 步骤 | 工具 | 关键参数 |
|------|------|----------|
| 1. 研报搜索 | **Tavily `tavily_search`** ⭐⭐⭐ | `query: "{企业名} 竞品 竞争格局 供应链"` |
| 2. 中文补充 | 博查 `bocha_web_search` ⭐⭐ | `query: "{企业名} 竞争对手 市场份额"` |
| 3. 国际视角 | Exa `web_search_exa` ⭐⭐ | `query: "{英文公司名} competitor"` |

**弃用**：天眼查 `get_competitors` — 返回同行业公司而非真正竞品。

### 🆕 关系网络

| 步骤 | 工具 | 关键参数 |
|------|------|----------|
| 1. **关系图谱** | **天眼查** `tyc: get_relation_graph` | `company_name: "企业全称"` |
| 2. **关系路径** | **天眼查** `tyc: get_relation_path` | `company_name + searchKey2` |
| 3. 对外投资 | 天眼查/企查查均可 | `searchKey: "企业全称"` |
| 4. 人脉关系 | **脉脉 `maimai-prospect`（必选）** | 采购/供应链决策人 |

> **天眼查 `get_relation_graph` + `get_relation_path` 为独有能力**，企查查无替代。

---

## 四官网提取三级降级

```
1. TinyFish fetch_content → 成功则用（最佳质量）
2. 失败 → Tavily tavily_extract(advanced) → 成功则用
3. 仍失败 → 跳过官网提取，用Tavily研报+博查新闻+天眼查get_products_info替代
```

---

## 五招投标四源互补策略

```
策略 1（已知企业-企查查）：企查查 get_bidding_info → 历史中标/投标记录
策略 2（已知企业-天眼查）：天眼查 get_bidding_info → 互为备选，交叉验证
策略 3（反向发现客户）：AnySearch 全局招标搜索 → 品类采购方发现
策略 4（第三方补充）：博查搜索"{产品品类} 招标 采购" → 补充招标平台数据
```

---

## 六并发调用依赖图

### 阶段 2.1：搜索层

```
7 路搜索全部可并发执行：
┌── 通道1: 天眼查 行业+区域  ──┐
├── 通道2: 天眼查 企业搜索   ──┤
├── 通道3: 博查/Tavily 竞品  ──┤  → 汇总 → 去重
├── 通道4: AnySearch 招标    ──┤
├── 通道5: Exa 海外          ──┤
├── 通道6: 东方财富 上市公司  ──┤
└── 通道7: 天眼查 融资搜索   ──┘
```

### 阶段 2.3：深挖层

```
对每个候选客户并发（天眼查+企查查双源并行）：
┌── ① 基本信息: 天眼查 basic_profile + 企查查 contact_info ──┐
├── ② 产品匹配: TinyFish官网 + 天眼查 products + 企查查专利 ─┤
├── ③ 采购潜力: **天眼查 suppliers_and_customers** + Tavily ──┤
├── ④ 决策人:   **天眼查 company_people** + 脉脉 ─────────────┤
├── ⑥ 风险评估: **企查查 risk_scan + credit_eval** + 天眼查 ──┤
├── ⑧ 产业链:   **天眼查 group_profile** + 企查查 invest ─────┤
├── ⑨ 动态:     博查 + 企查查 news/recruit/bidding + 东方财富─┤
├── ⑫ 竞品:     Tavily + 博查 + Exa ─────────────────────────┤
├── 🆕 关系:    **天眼查 relation_graph/relation_path** ──────┤
└── 🆕 融资:    **天眼查 financing_records** ──────────────────┘
```

---

## 七工具弃用清单

| 弃用工具 | 原因 | 替代方案 |
|---------|------|----------|
| 天眼查 `get_competitors` ❌ | 返回同行业公司而非真正竞品 | Tavily 研报 + 博查 + Exa |
| 天眼查全局 `search_bids` ❌ | 实测 0 结果 | 企查查/天眼查公司级 `get_bidding_info` + AnySearch |
| Exa/AnySearch 官网提取 ❌ | 内容极少或噪声大 | TinyFish → Tavily |
| Exa `web_fetch_exa` ❌ | 仅标题级内容 | TinyFish 或 Tavily |
| 八爪鱼 `bazhuayu` ❌ | HTTP 401 认证过期 | 无需替代 |
| Playwright ❌ | MCP 连接未建立 | 跳过官网 JS 单页兜底，用 Tavily 研报替代 |

---

## 八MCP 工具速查

### 天眼查 tyc-mcp — 广度优先（88 工具）

| 维度 | 关键工具 | 调用方式 |
|------|---------|----------|
| 企业搜索 | `search_companies` | 直接调用 `searchKey: "关键词"` |
| 行业区域搜索 | `search_companies_by_industry_region` | 直接调用 `industry + region` |
| 基本信息 | `get_company_basic_profile` | 直接调用 `company_name` |
| 人员 | `get_company_people` | 直接调用 `company_name` |
| 集团画像 | `get_company_group_profile` | 直接调用 `company_name` |
| 供应商/客户 | `call_tool → get_suppliers_and_customers` | `arguments: {page:1, page_size:10}` |
| 招投标 | `get_bidding_info` | 直接调用 `company_name` |
| 招聘 | `call_tool → get_recruitment_info` | `arguments: {page:1, page_size:20}` |
| 风险总览 | `get_risk_overview` | 直接调用 `company_name` |
| 产品信息 | `get_products_info` | 直接调用 `company_name` |
| 关系图谱 | `get_relation_graph` | 直接调用 `company_name` |
| 关系路径 | `get_relation_path` | `company_name + searchKey2` |
| 融资记录 | `get_financing_records` | 直接调用 `company_name` |
| 财务概要 | `get_financial_summary` | 直接调用 `company_name` |
| 专利 | `get_patent_info` | 直接调用 `company_name` |
| 新闻舆情 | `get_news_sentiment` | 直接调用 `company_name` |

### 企查查 qcc-mcp — 深度优先（6 Server，~40 工具）

| Server | 关键工具 | 用途 |
|--------|---------|------|
| `qcc-company` | `get_company_registration_info` | 工商登记 |
| `qcc-company` | `get_shareholder_info` | 股东 |
| `qcc-company` | `get_key_personnel` | 董监高 |
| `qcc-company` | `get_contact_info` | **8电话+9邮箱+5网址** |
| `qcc-company` | `get_external_investments` | 对外投资 |
| `qcc-company` | `get_actual_controller` | 实控人 |
| `qcc-risk` | `get_company_risk_scan` | **35因子一键扫描** |
| `qcc-operation` | `get_credit_evaluation` | **纳税+债券+海关+行业4维信用** |
| `qcc-operation` | `get_bidding_info` | 招投标 |
| `qcc-operation` | `get_recruitment_info` | 招聘(含薪资) |
| `qcc-operation` | `get_news_sentiment` | 新闻(附情感分类) |
| `qcc-ipr` | `get_patent_info` | 专利 |
| `qcc-executive` | `get_executive_positions` 等 | 高管个人维度 |

### 东方财富 mx-ds-mcp — 上市公司财务

| 用途 | 调用方式 |
|------|----------|
| 财务数据 | `mx_ashare_finance_data` 自然语言："XX公司 营收 利润 毛利率 PE PB 研发" |
| 新闻研报 | `mx_finance_search_news` 自然语言："XX公司 研报 2026" |
| 公告 | `mx_finance_search_notice` 自然语言："XX公司 公告 2026" |
| 选股筛选 | `mx_stocks_screener` 自然语言："通信设备行业 市盈率 营收" |

### 搜索引擎

| 工具 | 用途 | 调用方式 |
|------|------|----------|
| **博查** | 中文新闻/行业/展会 | `bocha_web_search(query, freshness, count)` |
| **Tavily** | 深度研报/IPO/竞品 | `tavily_search(query, max_results)` |
| **AnySearch** | 招标/展会/垂直搜索 | `search(query)` |
| **Exa** | 英文搜索/海外客户 | `web_search_exa(query, numResults)` |
| **TinyFish** | 网页提取/搜索 | `fetch_content(urls)` / `search(query)` |
| **Tushare** | A股基础确认 | `stock_basic(ts_code)` |