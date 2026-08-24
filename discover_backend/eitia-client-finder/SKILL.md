---
name: eitia-client-finder
description: >
  EITIA 客户发现——为电子信息产业链销售人员系统化寻找潜在客户。
  覆盖7大类场景：核心拓客、定向搜索、持续跟进(自动去重)、单企评估、竞品反推、机会扫描、区域/行业聚焦。
  三阶段工作流：会话感知(历史检测+去重)→需求澄清(三层漏斗式追问)→自动搜索+八维量化评分+并发深挖→Kami排版专业客户发现报告(PDF)。
  数据源双引擎：天眼查 tyc-mcp(88工具·广度优先)+企查查 qcc-mcp(6 Server·深度优先)双源互补，
  妙想/东方财富金融数据、脉脉决策人发现、博查/Tavily/AnySearch多引擎搜索。
  触发词：找客户、客户发现、客户开发、寻找潜在客户、拓客、找下游客户、找采购商、找买家、
  帮我找客户、XX产品卖给谁、找类似企业、帮我评估一下这家公司、竞品的客户有哪些、
  最近XX行业有什么机会、帮我验证线索、再帮我找几家新的不要重复、XX地区有没有做YY的、
  展会看到一家公司帮我看看、供应商验证、技术趋势下谁在升级。
version: "1.4"
model: opus
notes: >
  V5.4 模板化修复: ①CSS泄露修复(diff-table合并到style块+CSS变量列宽+render_report泄露检测),
  ②市场规模结构化(market_size升级为结构体{sub_segments}+三卡+分段表/mini-bar),
  ③产业链卡位EITIA四层(eitia_position升级为多层结构体+垂直堆叠条渲染),
  ④采购规模布局优化(间距缩小+公式折叠区+evidence_items 3→4),
  ⑤关键决策人gov_role硬门禁(check_gov_role函数+工商来源卡片必须含董监高角色),
  ⑥替代路径信息密度(substitution_path升级为steps[]时间线+每步含5字段),
  ⑦切换成本布局+条形图(switching_cost每维度升级为{value,label,sub_items}+子项列表),
  ⑧附录结构化(附录A≥10行表格/B含B.1~B.3子章节/C含≥5术语<dl>/D含≥3段<dl>+check_appendix_density),
  3文件协同: HTML模板+Python验证器+SKILL.md规则硬化。端到端验证: 0错误0警告。
compatibility: >
  MCP 双引擎：tyc-mcp(天眼查·集团/供应链/搜索)+qcc-mcp(企查查6 Server·信用/新闻/联系)。
  mx-ds-mcp(妙想/东方财富)、bocha-search-mcp(博查)、tavily-remote-mcp(Tavily)、
  exa(Exa)、anysearch(AnySearch)、tinyfish(TinyFish)、tushareMcp(Tushare)、
  playwright(浏览器交互)。
  需要 Skill：maimai-prospect(脉脉·VIP3)、kami(报告排版)。
  bazhuayu(八爪鱼)当前不可用(HTTP 401)，已排除。
---

# EITIA 客户发现 Skill

## 1. 概述与定位

本 Skill 为电子信息产业链销售人员提供系统化的潜在客户发现服务。隶属于 EITIA 电子信息产业链专属 Agent 的 7 大场景之一。

**核心原则**：
- **灵活输入**：最少只需告诉"卖什么"，越详细结果越精准
- **全自动执行**：除需求澄清阶段外无人工干预
- **数据驱动**：量化评分替代主观判断
- **专业交付**：Kami 排版 PDF 报告

**数据源双引擎**：
- **天眼查 tyc-mcp**（88工具，广度优先）：集团画像、供应商/客户、高管薪酬履历、企业搜索、关系图谱、融资——企查查无替代的独有能力
- **企查查 qcc-mcp**（6 Server，深度优先）：35因子风险扫描、4维信用评价、新闻情感分类、联系方式丰富度——特定维度优于天眼查
- 两者**双源互补**，42%天眼查独有 + 25%企查查更强 + 33%共有互为备选

**适用场景速览**：

| 类别 | 说明 | 典型问法 |
|------|------|----------|
| A. 核心拓客 | 以产品为锚点找客户 | "我卖高速背板连接器，帮我找客户" |
| B. 定向搜索 | 按条件筛选客户 | "汽车电子行业里做域控制器的厂商" |
| C. 持续跟进 | 第 N 次使用，自动去重 | "上次那5家联系完了，再找5家新的" |
| D. 单企评估 | 快速评估已知企业 | "帮我评估一下XX公司值不值得跟进" |
| E. 竞品反推 | 从竞品逆向发现客户 | "安费诺的客户有哪些？" |
| F. 机会扫描 | 宏观趋势找机会 | "最近数据中心交换机行业有什么新机会？" |
| G. 区域聚焦 | 按区域/产业带深耕 | "华东地区的汽车电子客户" |

---

## 2. 场景路由

收到用户输入后，按以下决策树判定场景类别。详细路由规则见 `references/scene-routing.md`。

**决策树概要**：
1. 输入含企业名称 → D 类（单企）或 E 类（竞品反推）
2. 输入含"上次/再/刷新/重新/除了" → C 类（持续跟进）
3. 输入含产品/能力描述 → A 类（核心拓客）或 B/G 类（条件搜索）
4. 输入含"最近/机会/热点/趋势/政策" → F 类（机会扫描）
5. 仅有模糊意图 → 进入标准 A1 流程

**场景→执行路径速查**：场景判定后，加载 `references/scene-routing.md` 获取该类场景的完整执行路径。

---

## 3. 输入规范

### 必填字段

| 字段 | 说明 | 获取方式 |
|------|------|----------|
| 产品/能力描述 | 卖什么产品、做什么业务 | 用户输入 或 阶段1 追问 |

### 可选字段（含默认值）

| 字段 | 默认值 | 用途 |
|------|--------|------|
| 目标行业 | 不限 | 天眼查行业过滤 / 博查关键词过滤 |
| 目标区域 | 全国 | 天眼查区域过滤 / 博查关键词过滤 |
| 客户规模 | 不限 | 初筛规模过滤 |
| 排除条件 | 无 | 排除过滤器 |
| 销售节奏 | 均衡 | 评分权重调整（急单→时机权重+5%，Pipeline→匹配权重+5%） |
| 报告数量 | 5 家 | 用户可指定 1-20 |

---

## 4. 阶段 0：会话感知（历史检测与去重）

在进入需求澄清之前，先执行历史会话检测。

### 步骤

1. 检查 `.cache/recommendation-history.json` 是否存在，不存在则跳过本阶段
2. 提取用户输入中的产品关键词 + 目标行业
3. 调用去重脚本进行匹配：
   ```bash
   echo '{"mode":"exclude","product_keywords":["提取的关键词"],"target_industry":"提取的行业"}' | python scripts/dedup_manager.py
   ```
4. 若匹配到相似线索（相似度 ≥ 0.7）→ 告知用户，呈现 A/B/C 三个选项
5. 若未匹配 → 按新线索正常进入阶段 1

### 匹配成功时的话术

告知用户：首次搜索时间、上次推荐企业数量、后备池剩余候选数量、选项 A/B/C

### 排除过滤器

- 自动排除：历史记录中所有 `status="已推荐"` 的企业（按 USCC 匹配）
- 手动排除：解析用户输入中的排除列表

---

## 5. 阶段 1：需求澄清（三层漏斗式追问）

唯一的人机交互窗口。加载 `references/tier-funnel-prompts.md` 获取标准话术。

- **第一层（必须问）**：产品/能力描述
- **第二层（默认追问）**：应用场景 / 差异化优势 / 标杆客户 / 竞品
- **第三层（按需追问）**：目标行业 / 区域 / 规模 / 排除 / 节奏 / 数量

---

## 6. 阶段 2：自动搜索 + 评分 + 深挖

加载 `references/data-source-mapping.md` 获取精确的工具调用参数和降级策略。

### 6.0 阶段门禁（Gate Check）—— 不可跳过

> ⚠️ 在进入下一阶段前，必须逐项确认以下门禁条件。**未通过的门禁不能进入下一步**。每道 Gate 是一个显式的自检步骤——AI 必须在回复中逐条报告 Gate 状态。

#### Gate 0 → Gate 1（需求澄清 → 搜索）

- [ ] 产品/能力描述已确认
- [ ] 目标行业/区域/规模/排除条件已确认（或使用默认值）
- [ ] 销售节奏和报告数量已确认
- [ ] 阶段 0 历史检测已完成（若有历史记录）

#### Gate 1 → Gate 2（搜索 → 初筛）

- [ ] 候选池 ≥ 15 家企业（含后备池，不足则扩展搜索条件重搜）
- [ ] 每家企业至少完成初筛（天眼查 `basic_profile` + 企查查 `contact_info`）
- [ ] 排除过滤器已生效（已推荐企业排除 + 红线一票否决排除）

#### Gate 2 → Gate 3（初筛 → 深挖）

- [ ] 深挖队列已确定（通常 5-8 家）
- [ ] 每企业并发深挖维度 ≥ 5（需覆盖 §6.4 全部 8 个 section 的数据源）
- [ ] **脉脉数据已采集**（`python scripts/maimai_search.py --companies "企业列表" --auth .maimai-auth.json` 已执行且输出非空）或标注"Playwright 环境不可用，降级为工商董监高"
- [ ] **股权架构数据已采集**（天眼查 `get_shareholder_info` + 企查查 `get_actual_controller`）
- [ ] **竞品数据已采集**（Tavily + 博查 + Exa，每企业 ≥ 3 家竞品）
- [ ] **竞品数据来源已交叉验证**
- [ ] **上市状态已交叉验证**（每企业通过东方财富 `stock_basic` + 天眼查 `search_listed_companies` 确认上市属性，不得凭注册资本推断。basic_table 必须包含"上市状态"行）
（每个竞品的市场份额至少 2 个独立信息源确认；无法交叉验证的须标注"（单源估计）"）



> **漏斗数字约束（V5.4.3）**：候选池数量 > 初筛数量 > 深挖数量 > 推荐数量。各级之间至少差 3 家以上。推荐数量 = `l0.top_n`（默认 5）。深挖数量 = 推荐数量 × 1.5（至少比推荐多 2 家）。

#### Gate 3 → Gate 4（深挖 → 评分 → JSON）

- [ ] `score_calculator.py` 已运行且输出有效（见 §6.5 强制步骤）
- [ ] 8 维子分数（`match_subscore_1`~`match_subscore_8`）全部非 0
- [ ] 每维子分数有 `sub_scores`（原始子维度分数）、`raw_data`（依据数据）、`source`（数据来源）
- [ ] 采购规模推算有明确 `base_calc.formula`（推算公式）和 `base_calc.base_source`（推算基数来源）
- [ ] `l0.industry` 结构体的 5 项子组件完整（市场规模/产业链卡位/客户地图/竞品格局/趋势）
- [ ] `equity_section` 内容 ≥ 100 字符（含实控人+前 3-5 大股东+结构简述+来源）
- [ ] `market_size` 已从旧格式 {value, source} 升级为 V5.4 结构体 {amount, unit, yoy_growth, year, source, sub_segments}（非纯文本段落）
- [ ] `eitia_position` 含 upstream_layers/downstream_direct/downstream_indirect 多层结构（非旧格式 {tier, upstream, description}）
- [ ] 每条 contact_card 的 `gov_role` 字段已对工商来源卡片填写
- [ ] `substitution_path` 的 steps ≥ 3 且每步包含 phase/action/duration/barrier/owner
- [ ] `switching_cost` 各维度含 sub_items（非单值字符串）
- [ ] 附录 A 数据日志包含 ≥ 10 行数据采集记录
- [ ] 附录 B 包含 B.1/B.2/B.3 三个子章节标记
- [ ] 附录 C 包含 ≥ 5 个术语（&lt;dl&gt; 格式）
- [ ] 附录 D 包含 ≥ 3 段免责声明
- [ ] JSON 生成使用 Write 工具直接写入（严禁 bash -c 内联生成）


> **V5.3: 8 维标准名称表**（模板 JSON 附录三者必须统一使用）

| # | 标准 label | 权重 | 对应 scoring-rules 维度 |
|---|-----------|:---:|------|
| 1 | 采购规模 | 20% | 维度 1：采购规模估算 |
| 2 | 技术匹配 | 20% | 维度 2：产品技术匹配度 |
| 3 | 需求强度 | 15% | 维度 3：需求强度 |
| 4 | 采购时机 | 15% | 维度 4：采购时机 |
| 5 | 竞争位置 | 10% | 维度 5：竞争位置 |
| 6 | 触达可行 | 10% | 维度 6：触达可行性 |
| 7 | 决策复杂度 | 5% | 维度 7：决策复杂度 |
| 8 | 信用安全 | 5% | 维度 8：企业信用安全 |

> `match_subscore_1~8` 的 `label` 字段必须使用以上标准名称。`render_report.py` 进行一致性验证（V5.3 新增）。

#### Gate 4 → Gate 5（JSON → 报告渲染）

- [ ] `render_report.py --check-only` 全部通过（零错误）
- [ ] L0 行业全景密度检查通过
- [ ] 无工具名泄漏、无残留未渲染变量

**执行纪律**：每道 Gate 通过后才能进入下一阶段。若某 Gate 未通过，必须在原地修复后重新检查，不得跳过。

### 6.1 排除过滤器生效

将阶段 0 生成的排除列表注入所有搜索步骤。

### 6.2 多路并发搜索（7 路可并发）

> ⚠️ **硬约束**：第一批搜索必须在一个 tool_call 批次中同时发出 ≥ 6 个工具调用（覆盖 7 路中的至少 5 路 + 行业搜索的博查/Tavily）。不得在搜索阶段分批逐步追加。如果某路因为参数不确定需要先确认，必须由其他路补到 6 个。

| 通道 | 工具 | 策略 |
|------|------|------|
| 行业+区域 | **天眼查** `search_companies_by_industry_region` | EITIA 层级推断 → 锁定目标层级 |
| 企业搜索 | **天眼查** `search_companies` | 产品/行业关键词精确搜索 |
| 竞品倒推 | 博查 + Tavily | `"{竞品} 客户 供应链"` |
| 招标反推 | AnySearch | `"{产品品类} 招标 采购"` |
| 海外补充 | Exa `web_search_exa` | 英文关键词搜索 |
| 上市筛选 | 东方财富 `mx_stocks_screener` | 行业筛选上市公司 |
| 融资搜索 | **天眼查** `get_financing_records` | 发现获投企业及其客户 |
| 脉脉人脉 | **脉脉** `maimai-prospect` Skill | **必选**——深挖队列确定后，对每家企业并发调用；小团队(<20人)覆盖率为0时降级为工商董监高 |

> 天眼查不可用时，通道1-2降级为博查/Tavily 关键词搜索。
> 通道8（脉脉）仅在深挖层触发——第7路会先用企业名录确定入选企业，再并发发起脉脉搜索。

### 6.3 初筛与后备池

对候选池逐企快速初筛（**天眼查 `get_company_basic_profile` + 企查查 `get_contact_info`**）：

- 🚫 信用红线一票否决 → 直接排除
- ✅ 初筛通过 → 进入深挖队列
- ⚠️ 未达阈值但相关 → 存入后备池

### 6.4 并发深挖（天眼查+企查查双源并行）

> ⚠️ **硬约束**：深挖第一批必须在一个 tool_call 批次中同时发出 ≥ 20 个工具调用。公式：N 家企业 × 至少 4 个维度（①工商 + ⑧风险 + ④高管 + 行业/招标补充）= N×4。例如 5 家企业 × 4 = 20 次调用。不得分批逐步追加——缺的维度在第二批中并发补齐，同样不低于 10 次调用。

每客户至少覆盖以下维度，以报告 section 1.1-1.8 是否填满作为数据完整度的检查标准。未覆盖的维度在报告中标注"数据不完整"。

| # | 报告 Section | 维度 | 双源策略 | 降级 |
|---|-------------|------|----------|------|
| ① | 1.1 企业速览 | 工商+简介+Logo+标签+**股权架构(必填)** | **天眼查** `get_company_basic_profile` + **企查查** `registration_info`/`get_company_profile` + 天眼查 `get_shareholder_info` + 企查查 `get_actual_controller` | 博查 |
| ② | 1.2 匹配度诊断 | AI 综合评估 | —（AI 基于采集数据综合判断，必须用 score_calculator.py 计算评分） | — |
| ③ | 1.3 采购规模 | 融资+招聘+供应商/客户 | **天眼查** `get_financing_records`⭐ + `get_recruitment_info` + `get_suppliers_and_customers` ⭐ | Tavily+博查 |
| ④ | 1.4 关键决策人 | 高管列表+联系方式+履历+**脉脉(硬约束)** | **天眼查** `get_company_people`(薪酬+履历+核心团队) + 企查查 `get_key_personnel` + `get_contact_info` + **脉脉** `maimai-prospect`(在职员工，深挖层**必选，不可跳过**) | Exa people search / LinkedIn 公开页面 |

> **股权架构必填规则**：§6.0 Gate 2 → Gate 3 要求股权架构数据已采集。天眼查 `get_shareholder_info` + 企查查 `get_actual_controller` 必须在深挖第一批工具调用中包含。报告 `equity_section` 必须含：①实际控制人（姓名+持股比例/表决权比例+穿透路径简述）②前五大股东（名称+持股比例+股东性质分类[自然人/法人/国资/外资/PE]）③股权集中度判断（"高度集中"/"相对集中"/"较为分散"+判断依据）④股东性质分类统计 ⑤数据来源标注。内容不足 100 字符将触发 render_report.py 验证错误。

> **脉脉硬约束规则**：§6.0 Gate 2 → Gate 3 要求脉脉数据已采集。深挖队列确定后，**必须**在第一批并发工具调用中：
> 1. 对每家企业调用 `maimai-prospect` Skill（需 Playwright MCP + 企查查 MCP(公司锚定) + 脉脉 VIP 3）
> 2. 脉脉结果处理：有结果 → 筛选采购/研发/技术总监级别 + 工商董监高 → 合并去重；覆盖率为 0 → 标注"公开社交平台未能识别到决策人" + 降级仅工商董监高
> 3. 每个 `contact_card` 标注来源标签（禁止附加"（已采集）"等状态标注）：`"脉脉"` / `"工商登记"` / `"企业官网"` / `"行业推断"`
> 4. 小团队(<20人)脉脉覆盖率低(0-14%)属正常现象，不视为采集失败。覆盖率=0 时标注降级信息。
> 5. render_report.py 强制检查 contact_cards 中是否有脉脉来源或降级标注
> 5. **V5.3: 董监高角色标注**：如果该决策人同时是工商登记的董监高（天眼查 get_company_people 或企查查 get_key_personnel 确认），contact_card 必须包含 gov_role 字段（如"董事""监事""总经理"）。模板自动展示为绿色小徽章。
| ⑤ | 1.5 动态信号 | 新闻+招聘+招标+产品 | **企查查** `get_news_sentiment`(情感分类) + 天眼查/企查查招聘+招标 + 博查/Tavily | — |
> **V5.3: 信号量化规则**：每条信号除 detail 文字外，应包含量化指标（可选 `metrics` 字段）

| 信号类别 | 量化指标 | 示例 metrics |
|---------|---------|-------------|
| 招聘 signal | 岗位数量 + 岗位类型 | {"岗位数": 45, "岗位类型": "嵌入式工程师/硬件工程师"} |
| 融资 signal | 金额 + 轮次 + 投资方 | {"金额": "2亿元", "轮次": "C轮"} |
| 招标 signal | 项目名称 + 金额 | {"项目": "XX工厂改造", "金额": "500万"} |
| 产品 signal | 新品名称 + 发布时间 | {"新品": "人形机器人控制器", "时间": "2026Q3"} |

> 纯描述性信号（如"正在招聘"）不可接收。render_report.py 检查 detail 是否含数字（V5.3 新增）。

| ⑥ | 1.6 切入策略 | AI 生成 | —（基于 1.1-1.5 的实际数据定制话术） | — |
> **V5.3: 切入点写作规范**：切入话题必须以行业趋势/技术变革/政策驱动/竞争格局等宏观分析开头。**禁止**"XX总曾说过""据XX人士"等人称视角。建议三层结构：趋势洞察(trend) → 与我方关联(relevance) → 具体话术(approach)。render_report.py 检测人物视角模式（V5.3 新增）。

| ⑦ | 1.7 竞品替代 | 供应商推断+竞品格局对比 | **天眼查** `get_suppliers_and_customers` ⭐ + Tavily 行业搜索 | 企查查投资关系 |
| ⑧ | 1.8 风险 | 35因子+信用评价 | **企查查** `get_company_risk_scan`(主力) + `get_credit_evaluation` + 天眼查 `get_risk_overview`(备选) | — |

> ⭐ = 天眼查独有能力，企查查无替代。天眼查不可用时此维度严重受限。

**采集纪律**：
- 每客户至少调用 **5 个不同维度的工具**，低于此阈值报告标注"数据不充分"
- 注册资本、参保人数、经营状态三项需天眼查+企查查双源交叉验证
- 动态信号标注数据日期，超过 6 个月标注"可能已过时"
- 报告附录 A 自动记录每次调用的维度+来源类型+时间
- **脉脉数据质量**：小团队(<20人)或初创 Fabless 的脉脉覆盖率低(0-14%)属正常现象，不视为采集失败。覆盖率为 0 时标注「公开社交平台未能识别到决策人」，降级使用工商登记董监高 + Exa people search

### 6.5 八维量化评分（强制使用计算器）

> ⚠️ **硬约束**：评分**必须**通过 `score_calculator.py` 计算，**禁止** AI 直接给出分数。跳过计算器直接评分是**一票否决的质量缺陷**。

#### 强制步骤

```
Step A: 按 scoring-rules.md 对每客户逐维度打分
  - 每个维度分解为子维度（参见 references/scoring-rules.md §二~§九）
  - 每个子维度记录：原始观察数据 + 数据来源
  - 汇总为维度总分（0-10）

Step B: 将原始分写入临时 JSON → 调用 score_calculator.py
  echo '{"companies":[{"company_name":"XX","uscc":"XX","scores":{...},"red_flags":{...}}],"top_n":5}' | python scripts/score_calculator.py
  → 得到加权综合分 + 排名 + 分类

Step C: 交叉验证
  - 若 score_calculator.py 输出的 composite_score 与手动估分偏差 > 0.5，以计算器为准
  - 若某维度分数为 0（数据缺失），标注为"数据缺失·取中性分"

Step D: 将计算器输出写回 JSON
  - c.score = ranking.composite_score
  - c.rank = ranking.rank
  - c.match_subscore_1.score ~ c.match_subscore_8.score = ranking.dimension_scores
  - 同时填写 sub_scores（子维度原始分）、raw_data（依据数据）、source（来源）
```

#### 评分输出规范（每个 match_subscore_N 必含字段）

| 字段 | 说明 | 示例 |
|------|------|------|
| `label` | 维度名 | "采购规模" |
| `score` | 维度得分（0-10） | 8.0 |
| `weight` | 权重 | "20%" |
| `sub_scores` | 子维度分数映射 | `{"产品线相关性":4, "企业体量":2, "增长趋势":2}` |
| `raw_data` | 原始数据依据 | "注册资本1亿+参保1000人+近期扩招30人" |
| `source` | 数据来源（泛化标签） | "企业公开登记信息""公开市场信息" |

详细规则见 `references/scoring-rules.md`。

### 6.6 数据时效性强制检查（生成 JSON 前执行）

> ⚠️ **硬约束**：在生成 JSON 数据文件之前，逐项检查以下时效性要求：

| 检查项 | 时效要求 | 检查方法 |
|--------|---------|----------|
| 行业规模数据 | 必须为当前年份或最近可获得的年份（2025 或 2026） | 检查 `l0.industry_overview` 中的年份引用 |
| 新闻/动态信号 | 每个信号必须标注日期，超过 6 个月的标注"可能已过时" | 逐条检查 `signals[].date` |
| 招聘信息 | 必须为近 3 个月内的发布 | 检查招聘数据的时间戳 |
| 招标信息 | 必须为当前年度或上一年度的在效标 | 检查招标公告日期 |
| 融资信息 | 标注融资轮次日期，超过 1 年的标注具体年份 | 检查融资记录日期 |

**硬约束**：报告中任何引用"2024 年"或更早年份的数据，必须有明确理由说明为何无法获取更新数据。否则必须重新搜索当前年份数据。

#### 6.6.2 事实断言的交叉验证规则

在报告中做出以下类型的事实断言前，必须至少有 2 个独立信息源确认：

| 断言类型 | 最少信息源 | 示例 |
|----------|:--------:|------|
| 技术来源/代码继承关系 | 2 个独立源 | "基于 XX 代码" ← 需官网+新闻双重确认 |
| 市场份额/排名 | 2 个独立源 | "市场第一" ← 需研报+行业报告 |
| 客户-供应商关系 | 2 个独立源 | "XX 是 YY 的供应商" ← 需工商数据+新闻 |
| 竞品能力对比 | 2 个独立源 | "XX 产品优于 YY" ← 需参数对比+评测 |

**硬约束**：单一信息源的断言，必须在报告中明确标注信息来源（如"据 XX 公司官网声称"）。对于推断性结论，使用"推断"/"可能"/"估计"等限定词。

#### 6.6.3 评分输出规范引用

> 完整评分输出规范见 §6.5（含 8 维子分数字段定义、sub_scores/raw_data/source 必填要求）。综合分（`c.score`）必须由 `score_calculator.py` 输出。

---

## 7. 阶段 3：Kami 报告生成

eitia-cfr 是注册在 Kami 模板库中的专属模板。每次生成报告时走以下管道。

**报告结构**（按销售决策需求组织，非按数据源堆砌）：

```
封面 → L0报告导读(30秒上手+评分速览+TOP N一览+优先级矩阵+市场全景[含行业背景])
     → L1单客户深度档案(每客户独立分页,8个section完全一致可横向对比)
        1.1 企业速览卡  1.2 匹配度诊断
        1.3 采购规模估算(★核心)  1.4 关键决策人(★核心)
        1.5 动态信号雷达  1.6 切入策略
        1.7 竞品替代分析  1.8 风险与注意事项
     → 附录A数据采集日志 → B评分方法论 → C术语解释 → D免责与使用建议
```

> **V5.1 结构变更**：原独立 L2「行业背景」已并入 L0 报告导读的第 5 个子节；原 L3「行动手册」已拆入 L1 各客户档案的 1.4(关键决策人) + 1.6(切入策略)。不再有 L2/L3 层级。报告实际输出为：封面(1页) → L0 导读(1-2页) → L1×N 客户档案(N×2-3页) → 附录(2-3页)。V5.1 加固脉脉硬约束（source 前綴匹配、CSS/Jinja2 工具名清理）。

**核心原则**：模板中的每个 section 是否被填满，直接反映数据是否拉取充分。AI 在填充报告时必须逐 section 检查完成度，缺失的 section 优先补齐数据而非用套话填充。

### 7.1 报告模式判定

- 首次调用 → 标准版报告
- 追加调用 → 增量版报告（含 L0 会话摘要）
- 线索刷新 → 动态更新报告

### 7.2 构建管道（Jinja2 渲染引擎）

```
Step A: AI 采集完所有 MCP 数据后，生成 JSON 数据文件
  → 路径: D:\ClaudeCode\Report\eitia_data_{产品简称}_{YYYYMMDD}.json
  → 结构按 assets/eitia-cfr.html 顶部的 Jinja2 注释 schema（V5-structured）
  → 所有 HTML 内容块由 AI 按模板 CSS class 要求生成
  → cover.company_name 可选填委托公司名称（在阶段 1 三层追问中获取）
  → ⚠️ 禁止通过 bash -c 内联生成 JSON（Shell 嵌套引号 + 中文编码双重陷阱，
    已验证在 Windows Git Bash / MSYS2 环境下 100% 失败）。
    必须使用 Write 工具直接写入 JSON 文件，再通过 Python 脚本验证。
  → ⚠️ 节 7.2.1 内容规范（颜色标注、格式要求）必须在生成 HTML 块时遵守
  → ⚠️ 节 7.2.2 内容密度基线表定义了每 section 的最低内容量

Step B: Jinja2 渲染
  python scripts/render_report.py D:\ClaudeCode\Report\eitia_data_{产品}_{日期}.json
  → 自动校验：JSON 完整性 + L0 行业全景密度 + 评分可追溯 + 推算公式 + 脉脉来源 + 渲染无异常 + 无残留变量 + 信息密度 + 工具名泄漏
  → 输出: D:\ClaudeCode\Report\EITIA_{产品简称}_{YYYYMMDD}_v{版本号}.html
```

### 7.2.1 HTML 内容块生成规范（颜色标注规则）

AI 在生成 JSON 中各 section 的 HTML 块时，必须遵守以下颜色标注规则，提升报告的可读性和信息密度：

| 场景 | CSS 类 / 颜色 | 用途 | 示例 |
|------|:-----------:|------|------|
| 匹配亮点中的关键价值 | `<span class="check-pass">` 绿色 | 标注对销售的积极价值 | `<span class="check-pass">→ 年采购额估算80-150万</span>` |
| 匹配风险中的影响说明 | `<span class="check-warn">` 黄色 | 标注需要注意的风险影响 | `<span class="check-warn">（影响：决策周期6-12个月）</span>` |
| 置信度·高 | `confidence-high` 绿色 | 基于公开财务或招标数据推算 | |
| 置信度·中 | `confidence-mid` 黄色 | 基于招聘+行业基准推算 | |
| 置信度·低 | `confidence-low` 红色 | 仅基于企业规模推断 | |
| 信号·积极 | `level: "green"` → 绿色 border-top | 扩产/融资/招标中标 | |
| 信号·中性 | `level: "yellow"` → 黄色 border-top | 招聘平稳/行业景气 | |
| 信号·负面 | `level: "red"` → 红色 border-top | 裁员/诉讼/营收下滑 | |
| 风险·低 | `level: "risk-low"` → 绿色左边框+浅绿底 | 常规经营风险 | |
| 风险·中 | `level: "risk-mid"` → 黄色左边框+浅黄底 | 需关注的经营风险 | |
| 风险·高 | `level: "risk-high"` → 红色左边框+浅红底 | 影响合作的关键风险 | |
| 壁垒·低 | `barrier-low` 绿底标签 | 进入壁垒低 | |
| 壁垒·中 | `barrier-mid` 黄底标签 | 进入壁垒中等 | |
| 壁垒·高 | `barrier-high` 红底标签 | 进入壁垒高 | |
| 数据来源·脉脉 | `contact-card-source maimai` 蓝底 | 标识脉脉采集的决策人 | |
| 数据来源·工商 | `contact-card-source gongshang` 灰底 | 标识工商登记的董监高 | |
| 差异化对比 | `.diff-table td:nth-child(2)` 红色 `.diff-table td:nth-child(3)` 绿色 | 竞品做法 vs 我方做法 | 竞品列红色、我方列绿色加粗 |

**硬约束**：HTML 块中禁止使用 `<a>` 标签、`<div>` 嵌套容器、`<!-- -->` HTML 注释。

### 7.2.2 内容密度基线表（每 section "多少算够"）

> V5.4 更新：新增 market_size、eitia_position、substitution_path、switching_cost、contact_card(gov_role)、appendix 的密度基线。

| Section | 最低内容量 | 推荐内容量 | 验证方式 |
|---------|:--------:|:--------:|----------|
| L0 行业全景 | 5 项子组件全部非空 | market_size 含 sub_segments ≥ 3、eitia_position 含 upstream_layers ≥ 1 + downstream_direct ≥ 1、customer_map ≥ 3、competitive_landscape ≥ 3、key_trends ≥ 3 | `check_l0_density()` |
| 1.1 企业速览 | KPI ≥ 4 项、股权 ≥ 100 字符 | 含 Logo/标签/位置图 | HTML 长度 + KPI 计数 |
| 1.2 匹配度诊断 | match_highlights ≥ 3 条、match_risks ≥ 2 条 | 每 highlight 含维度标签+事实+价值 | 数组长度检查 |
| 1.3 采购规模 | drivers ≥ 3、evidence_items ≥ 4 | base_calc.formula 有明确公式、coefficients ≥ 2 | base_calc.formula 非空 |
| 1.4 关键决策人 | contact_cards ≥ 2 张、工商来源卡片必须有 gov_role | ≥ 1 张有脉脉来源 | 脉脉来源检查 + `check_gov_role()` |
| 1.5 动态信号 | signals ≥ 4 条、每信号有 date + metrics | 覆盖招聘/融资/招标/产品 4 维度 | 数组长度 + date + metrics 检查 |
| 1.6 切入策略 | value_props ≥ 3、entry_points ≥ 3、timeline_steps ≥ 3 | objection_handlers ≥ 2 | objection_handlers 长度检查 |
| 1.7 竞品替代 | competitors ≥ 3、our_differentiation ≥ 3、substitution_path.steps ≥ 3 | switching_cost 各维度含 sub_items ≥ 2、current_supplier_inference 有推断依据 | `substitution_path.steps` 数组检查 |
| 1.8 风险 | risks ≥ 4 条 | 至少 1 条 risk-high | risk-high 存在性检查 |
| 附录 A | data_log 表格 ≥ 10 行 | 每行列: #/时间/目标/维度/来源类型 | `check_appendix_density()` |
| 附录 B | scoring_method 含 B.1/B.2/B.3 子章节 | ≥ 300 字符 | 子章节标记检查 |
| 附录 C | glossary ≥ 5 个 <dt> 术语 | 按报告中出现顺序排列 | <dt> 计数 |
| 附录 D | disclaimer ≥ 3 段 <p> | ≥ 150 字符 | <p> 计数 + 长度 |
  python scripts/render_report.py D:\ClaudeCode\Report\eitia_data_{产品}_{日期}.json
  → 自动校验：JSON 完整性 + L0 行业全景密度 + 评分可追溯 + 推算公式 + 脉脉来源 + 渲染无异常 + 无残留变量 + 信息密度 + 工具名泄漏
  → 输出: D:\ClaudeCode\Report\EITIA_{产品简称}_{YYYYMMDD}_v{版本号}.html

Step C: 部署 + 构建 + 验证（一键脚本）
  python scripts/deploy_pdf.py D:\ClaudeCode\Report\eitia_data_{产品}_{日期}.json
  → 自动完成：Jinja2渲染 → Kami部署 → PDF构建 → 内容验证(Jinja2残留检查) → 模板恢复
  → 输出: D:\ClaudeCode\Report\EITIA_{产品简称}_{YYYYMMDD}_v{版本号}.pdf
  → ⚠️ 必须使用 deploy_pdf.py，禁止手动 cp 到 Kami 模板目录（容易漏掉渲染步骤导致 PDF 含 {{ }} 残留）
```

> **Jinja2 渲染引擎优势**：模板 CSS/HTML 结构固定不变（`{% for c in clients %}` 处理循环），AI 只负责生成数据 JSON。同一份 JSON 每次渲染出完全相同的 PDF。渲染脚本自动校验 6 项（JSON 完整性 / 渲染异常 / 残留变量 / 信息密度 / 工具名泄漏 / section 完整性），不通过则拒绝输出。

### 7.3 build.py 验证项

| 检查项 | 说明 | 通过标准 |
|--------|------|:--:|
| WeasyPrint 渲染 | HTML→PDF | 无错误 |
| 字体嵌入 | TsangerJinKai02 | 中文正常 |
| 页数上限 | 0 (无限) | 不限制 |
| 密度检查 | 正文填充率 | 无 SPARSE 警告 |

### 7.4 模板注册记录与升级注意事项

- 模板名：`eitia-cfr`
- 注册位置：`$KAMI_DIR/scripts/shared.py` Line 129
- 模板文件：`$KAMI_DIR/assets/templates/eitia-cfr.html`
- 品牌色：`#059669` 翠绿
- 底色：`#f4f6f7` 冷灰白
- 页数上限：0 (无限)

> **Kami 升级后需要重新注册**：如果执行 `npx skills add` 升级 Kami，`shared.py` 会被覆盖。升级后需手动恢复注册行：
> ```bash
> # 1. 确认模板文件还在
> ls $KAMI_DIR/assets/templates/eitia-cfr.html
> # 2. 如果没有，从 skill assets 复制
> cp assets/eitia-cfr.html $KAMI_DIR/assets/templates/
> # 3. 重新注册
> python -c "
> p = '$KAMI_DIR/scripts/shared.py'
> with open(p, 'r') as f: c = f.read()
> old = '\"equity-report\":    TemplateSpec(\"equity-report.html\",    0),'
> new = old + '\n    \"eitia-cfr\":       TemplateSpec(\"eitia-cfr.html\",       0),'
> c = c.replace(old, new)
> with open(p, 'w') as f: f.write(c)
> " && python scripts/build.py --verify eitia-cfr

### 7.5 历史记录更新

```bash
echo '{"mode":"add","clue_data":{...}}' | python scripts/dedup_manager.py
```

## 8. 数据源能力矩阵（双引擎）

| 维度 | 工具 | 评级 |
|------|------|:--:|
| 企业搜索 | `search_companies` + `search_companies_by_industry_region` | ⭐⭐⭐ |
| 高管薪酬履历 | `get_company_people`（年薪+持股+核心团队） | ⭐⭐⭐ |
| 集团画像 | `get_company_group_profile`（215成员+实控人） | ⭐⭐⭐ |
| 供应商/客户 | `call_tool → get_suppliers_and_customers` | ⭐⭐⭐ |
| 关系图谱 | `get_relation_graph` + `get_relation_path` | ⭐⭐⭐ |
| 融资历史 | `get_financing_records` | ⭐⭐⭐ |
| 产品信息 | `get_products_info` | ⭐⭐ |

### 企查查更强 🏆（特定维度优于天眼查）

| 维度 | 工具 | 评级 |
|------|------|:--:|
| 信用评价 | `get_credit_evaluation`（纳税+债券+海关+行业4维） | ⭐⭐⭐ |
| 新闻情感 | `get_news_sentiment`（附积极/中立/消极分类） | ⭐⭐⭐ |
| 联系方式 | `get_contact_info`（8电话+9邮箱+5网址） | ⭐⭐⭐ |
| 风险扫描 | `get_company_risk_scan`（35因子一键扫描） | ⭐⭐⭐ |

### 共有互为备选 ⚖️

| 维度 | 工具 | 评级 |
|------|------|:--:|
| 工商信息 | 天眼查 `basic_profile` + 企查查 `registration_info` | ⭐⭐⭐ |
| 股东 | 天眼查 `shareholder_info` + 企查查 | ⭐⭐⭐ |
| 招投标 | 天眼查 `get_bidding_info` + 企查查 | ⭐⭐⭐ |
| 招聘 | 天眼查 `get_recruitment_info`(含链接) + 企查查(含薪资) | ⭐⭐⭐ |
| 专利 | 天眼查 `get_patent_info` + 企查查 | ⭐⭐⭐ |
| 财务 | **东方财富** `mx_ashare_finance_data`（最优） | ⭐⭐⭐ |
| 搜索动态 | 博查 + Tavily + AnySearch + Exa | ⭐⭐⭐ |

### 弃用清单

| 弃用工具 | 原因 | 替代 |
|---------|------|------|
| 天眼查 `get_competitors` | 返回同行业公司非真正竞品 | Tavily + 博查 + Exa |
| Exa/AnySearch 官网提取 | 内容极少/噪声大 | TinyFish → Tavily |
| 八爪鱼 `bazhuayu` | HTTP 401 认证过期 | — |

---

## 9. 执行规范与约束

### 并发控制

> ⚠️ **阶段 2 执行前自检**（每批次前强制检查）：
> □ 搜索批：第一批同时发出 ≥ 6 个工具调用（覆盖 7 路中的至少 5 路）
> □ 深挖批：同一批次覆盖所有入选企业，每企业 ≥ 4 个维度（N×4 ≥ 20）
> □ 每批次完成后：检查遗漏 → 补发（再次并发，不是逐个补）
> □ 全部数据就绪后：一次性生成 JSON → Jinja2 渲染

- 搜索层：7 路全部并发，第一批 ≥ 6 个工具调用
- 深挖层：企业间并发，每家企业内部**天眼查+企查查双源并行**，然后再按维度并发。第一批 ≥ N×4 个工具调用
- 单个数据源超时 30 秒 → 降级

### 双引擎降级规则

```
优先路径：天眼查 + 企查查 双源并行
  ├── 天眼查可用 + 企查查可用 → 双源互补（最优）
  ├── 天眼查可用 + 企查查不可用 → 天眼查全承担（企查查强项维度降级标注）
  ├── 天眼查不可用 + 企查查可用 → 企查查为主（天眼查独有能力严重缺失，见下方）
  └── 两者均不可用 → 博查/Tavily/东方财富 仅搜索层 + 报告标注"数据源受限"

天眼查不可用时的关键损失（企查查无法替代）：
  - 集团画像 → 用企查查对外投资+股东推断集团结构
  - 供应商/客户 → 用Tavily研报+博查搜索"XX公司 供应链"补充
  - 高管薪酬履历 → 仅企查查 get_key_personnel（缺薪酬/持股/核心团队）
  - 行业批量搜索 → 博查关键词搜索
  - 关系图谱 → 仅企查查投资+股东关系
  - 融资记录 → Tavily搜索"XX公司 融资"
```

### 错误处理
- 单个数据源失败 → 降级到备用方案，报告中标注"数据不完整"
- 全部搜索通道无结果 → 告知用户并建议扩展条件
- 脉脉登录态过期 → 提示重新登录，其他数据源继续

### 信用红线
- 失信/破产/吊销/严重违法 → 一票否决

---

## 10. 输出检查清单

### 报告完整性（按 V5 8-section 结构）
- [ ] L0：报告导读（30秒上手 + 行业全景[5项子组件完整] + 候选池全景 + 信号热力图 + TOP N一览）
- [ ] L0 行业全景密度：market_size 含年份数字、customer_map ≥ 3、competitive_landscape ≥ 3、key_trends ≥ 3
- [ ] L1 × N（每客户 8 个 section 全部检查）：
  - [ ] 1.1 企业速览卡（工商+标签+KPI数字+一句话定位+**股权架构必填**）
  - [ ] 1.2 匹配度诊断（8维分数可追溯[sub_scores/raw_data/source]+亮点≥3条+风险≥2条+一票否决结果）
  - [ ] 1.3 采购规模估算（定量区间+**推算公式[base_calc.formula]**+证据链≥3条+当前供应商分析）
  - [ ] 1.4 关键决策人（≥2张决策人卡片+**脉脉来源标注**+决策链推断）
  - [ ] 1.5 动态信号雷达（≥4条信号+每条有date+覆盖融资/招聘/招标/产品）
  - [ ] 1.6 切入策略（定位话术+价值主张≥3+切入话题≥3+**异议预判≥2**+行动时间线≥3）
  - [ ] 1.7 竞品替代分析（竞品格局≥3家+**当前供应商推断**+替代路径+**切换成本**+四维壁垒+差异化优势≥3）
  - [ ] 1.8 风险与注意事项（≥4条风险+至少1条risk-high+每条有对策）
- [ ] 附录A：数据采集日志（列出所有MCP调用的维度+来源类型+时间）
- [ ] 附录B：评分方法论（公式+各维度权重+打分细则+红线规则）
- [ ] 附录C：术语解释（覆盖报告中出现的关键技术名词）
- [ ] 附录D：免责声明与使用建议

### 交付
- [ ] Kami PDF 已生成，`build.py --verify eitia-cfr` 返回 OK
- [ ] `render_report.py` 全部 6 项校验通过（无残留变量、无工具名泄漏、信息密度足够）
- [ ] JSON 数据文件已存档 `D:\ClaudeCode\Report\eitia_data_{产品}_{日期}.json`
- [ ] 每客户至少 5 个数据维度覆盖（JSON 中 HTML 内容块非空）
- [ ] 输出路径：`D:\ClaudeCode\Report\EITIA_{产品}_{YYYYMMDD}_v{版本号}.pdf`
- [ ] 推荐历史已写入 `recommendation-history.json`

---

## 附录：快速参考

| 需要什么 | 去哪里找 |
|---------|---------|
| 场景路由规则 | `references/scene-routing.md` |
| 三层追问话术 | `references/tier-funnel-prompts.md` |
| EITIA 四层架构 | `references/eitia-architecture.md` |
| 数据源调用方式 | `references/data-source-mapping.md` |
| 评分详细规则 | `references/scoring-rules.md` |
| 报告 Markdown 模板 | `references/report-structure.md` |
| 用户使用手册 | `references/user-guide.md` |

| 需要执行什么 | 用什么脚本 |
|-------------|-----------|
| 八维评分计算 | `scripts/score_calculator.py` |
| 去重匹配/排除/添加 | `scripts/dedup_manager.py` |
