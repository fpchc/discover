---
skill_id: client-finder
version: "1.5"
description: 客户发现——为电子信息产业链销售寻找潜在客户，八维量化评分并输出专业报告
scope:
  applies: 需要找/开发/评估潜在客户、竞品客户反推、行业机会扫描、区域产业带聚焦时
  does_not_apply: 纯闲聊、与企业获客无关的通用咨询、非电子信息产业链的销售场景
keywords: [找客户, 客户发现, 拓客, 潜在客户, 评估公司, 竞品客户, 机会扫描, 区域聚焦, 买什么, 卖给谁]
capability_dependencies:
  - capability: enterprise_business
    core_tools: []
    required: false
  - capability: enterprise_risk
    core_tools: []
    required: false
  - capability: financial_data
    core_tools: []
    required: false
  - capability: web_search
    core_tools: []
    required: true
scripts:
  - path: scripts/score_calculator.py
    name: score_calculator
    description: 八维量化评分计算器。评分必须经此脚本，禁止直接给出综合分
    schema_path: schemas/score_input.json
  - path: scripts/dedup_manager.py
    name: dedup_manager
    description: 推荐历史去重 / 排除列表生成 / 后备池激活排序
    side_effect: write_file
    history_store: true
    schema_path: schemas/dedup_input.json
  - path: scripts/render_report.py
    name: render_report
    description: 客户发现报告 HTML 渲染与结构校验（下一阶段启用；本阶段直接输出文字报告，不调用）
    side_effect: write_file
    schema_path: schemas/render_input.json
documents:
  - path: references/scene-routing.md
    when: 判定七类场景路由分支时
  - path: references/tier-funnel-prompts.md
    when: 阶段 1 需求澄清（三层漏斗追问）时
  - path: references/data-source-mapping.md
    when: 数据采集维度与数据能力映射
  - path: references/scoring-rules.md
    when: 八维评分子维度细则与权重
  - path: references/architecture.md
    when: 产业链层级推断与上下游定位
  - path: references/report-structure.md
    when: 报告 JSON 结构与各 section 填充要求
  - path: references/user-guide.md
    when: 向用户解释能力边界与使用方法
gates:
  - id: candidate_pool
    condition: 候选池 ≥ 5 家（P1 数据受限，不足时向用户说明并继续）
    blocking: false
  - id: score_valid
    condition: 每客户 8 维子分均非 0 且 score_calculator 输出有效
    blocking: false
  - id: render_pass
    condition: 本阶段交付文字报告，不生成 HTML；HTML 渲染与结构校验门禁于下一阶段（HTML 阶段）恢复
    validator: scripts/gate_render_valid.py
    schema_path: schemas/gate_input.json
    blocking: false
templates:
  - path: templates/cfr.html
    purpose: 客户发现报告 HTML 模板（Jinja2，下一阶段 HTML 渲染时启用）
---
# 客户发现工作流（P1 数据受限版）

## 0. 定位与场景

为电子信息产业链销售人员系统化发现潜在客户。七大类场景（核心拓客 / 定向搜索 / 持续跟进 / 单企评估 / 竞品反推 / 机会扫描 / 区域聚焦）**合并为本技能内的路由分支**，由场景判定规则分支，不拆成多个技能。场景判定见 `references/scene-routing.md`。

## 1. 阶段 0：会话感知（去重）

1. 用 `dedup_manager`（mode=exclude）读取历史推荐，输入产品关键词 + 目标行业。
2. 返回相似线索（相似度≥0.7）→ 向用户给出 A/B/C（激活后备池 / 全新搜索 / 刷新推荐）；无匹配则直接进阶段 1。
3. 历史已推荐企业自动进入排除列表；用户排除条件一并生效。

## 2. 阶段 1：需求澄清（三层漏斗追问）

唯一人机交互窗口，话术见 `references/tier-funnel-prompts.md`。
- 第一层（必问）：产品/能力描述，信息不足必须追问。
- 第二层（默认）：应用场景 / 差异化优势 / 标杆客户 / 竞品，可说「跳过」。
- 第三层（按需）：目标行业 / 区域 / 规模 / 排除 / 节奏 / 报告数量，缺省用默认值。
- 完成需求总结确认后再进入阶段 2。

## 3. 阶段 2：搜索 → 初筛 → 评分

### 3.1 搜索与初筛（数据受限）
数据源由平台装配的数据能力提供（企业专有数据能力 + 联网搜索）。多路关键词并发：产品名+行业、行业+区域、竞品+客户/供应链、招标/机会词。
- 候选池不足 5 家 → 扩展关键词 / 放宽区域重搜；仍不足则明确告知用户。
- 初筛：仅凭公开信息判断，信用红线一票否决（失信 / 破产 / 吊销 / 严重违法）直接排除；其余入深挖队列或后备池。
- 排除过滤器生效。

### 3.2 深挖（尽力而为 + 显式标注）
对深挖队列逐企采集公开信息，维度：① 工商速览 ② 主营与产品 ③ 采购规模线索（扩产/招聘/招标）④ 关键决策人（工商登记董监高；公开社交平台未能识别则标注降级）⑤ 动态信号（须带日期，超 6 个月标注「可能已过时」）⑥ 风险 ⑦ 竞品格局 ⑧ 产业链定位（`references/architecture.md`）。
- 应尽可能批量并发搜索，覆盖多维度；P1 无硬性最低调用数。
- 事实断言（技术来源 / 份额 / 客户关系 / 竞品对比）须 ≥2 独立来源；单源断言必须标注来源；推断用限定词。

### 3.3 八维评分（强制计算器）
1. 按 `references/scoring-rules.md` 逐维打子分（0-10），记录依据与来源。
2. 写临时 JSON → 调用 `score_calculator`（**必须经脚本，禁止 AI 直接给综合分**）。
3. 输出写回：综合分 / 排名 / 8 维子分。数据缺失维度取中性分并标注「数据不充分·取中性分」。
4. 信用安全 < 3.0 或触发红线 → 直接排除。

### 3.4 门禁
- `candidate_pool` 候选池 ≥ 5 家：尽力，不足向用户说明。—— 警告级
- `score_valid` 每客户 8 维子分非空且计算器输出有效。—— 警告级
- `render_pass` 报告结构校验（下一阶段 HTML 渲染时启用）。—— 本阶段降为警告级，不阻断文字报告交付。

## 4. 阶段 3：文字报告交付（本阶段；HTML 渲染为下一阶段）

1. 按 `references/report-structure.md` 的内容结构组织报告（封面信息 / 导读 / 客户深度档案 / 附录），但**直接输出为完整 Markdown 文字报告**作为最终回复；**不调用 `render_report`、不生成 HTML、不跑 `gate_render_pass`**（HTML 渲染与其结构校验门禁属下一阶段）。
2. 文字报告建议结构：
   - **封面信息**：委托方、产品/能力、目标行业与区域、报告日期、数据来源受限说明。
   - **报告导读**：执行摘要（推荐结论）、行业全景（市场规模 / 产业链卡位 / 竞争格局）、候选池漏斗、TOP N 客户一览（综合分排序）。
   - **每客户一章**：企业速览 → 八维匹配诊断（含权重与依据）→ 采购规模估算 → 关键决策人 → 动态信号（带日期）→ 切入策略（定位 / 价值主张 / 切入点 / 异议预判 / 时间线）→ 竞品替代分析 → 风险与注意事项。
   - **附录**：数据采集日志（工具来源）、评分方法论、免责声明。
3. 报告以 Markdown 正文流式输出（打字机效果）交付；数据缺口显式标注「P1 数据受限」/「数据不充分·取中性分」，不静默编造。

## 5. 报告质量预期管理（P1）

- 封面 / 导读明确标注「数据来源受限版本：公开搜索」。
- 数据不充分维度标「数据不充分·取中性分」；无决策人信息标「公开社交平台未能识别到决策人」。
- 附录 A 数据日志记录工具来源，突出实际使用的搜索工具（`web_search` 系列），让读者明确数据范围。
- 专有工商库维度（股权 / 集团穿透等）P1 标记受限。

## 6. 执行纪律

- 先澄清再搜索，不跳过第一层必问。
- 评分必须走 `score_calculator`，禁止手算综合分。
- 本阶段交付完整 Markdown 文字报告，不生成 HTML；HTML 渲染与 `gate_render_pass` 门禁属下一阶段。
- 尽力采集 + 显式标注，绝不对数据缺口静默编造。
