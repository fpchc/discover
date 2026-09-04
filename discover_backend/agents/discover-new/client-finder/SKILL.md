---
skill_id: client-finder
version: "3.3"
description: 客户调研——为销售调研潜在客户信息，候选池评分后推荐最优一家，输出 200~450 字信息卡
scope:
  applies: 销售调研客户信息、从候选池推荐最优客户、售前情报收集时
  does_not_apply: 需要完整八维长篇客户发现报告、非电子信息产业链调研的通用咨询、纯闲聊
keywords: [客户调研, 调研客户, 客户信息, 最优客户, 推荐客户, 工商信息, 主营业务, 销售情报]
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
    description: 八维量化评分计算器（含 Score Trace）。仅候选池场景使用，评分必须经此脚本
    schema_path: schemas/score_input.json
documents:
  - path: references/evidence-rules.md
    when: 证据等级判定、缺项是否补搜时
  - path: references/scoring-rules.md
    when: 候选池评分子维度与权重（仅候选池场景）
  - path: references/architecture.md
    when: 候选池场景产业链层级推断
gates:
  - id: candidate_pool
    condition: 候选池 ≥ 3 家（不足向用户说明并继续）
    blocking: false
  - id: score_valid
    condition: 每客户 8 维子分均非 0 且 score_calculator 输出有效（含 trace）
    blocking: false
  - id: final_qa
    condition: Final QA（单企 2 问 / 候选池 4 问）通过
    validator: scripts/gate_final_qa.py
    schema_path: schemas/final_qa_input.json
    blocking: true
---
# 客户调研工作流（一次调研版）

交付物：单企为一张 200~450 字信息卡；多企输入时逐家各出一张、全部输出（重点分层：结论 → 事实 → 价值）；目标是一次调研完成，禁止多次往返、禁止长链条思考。

## 1. 场景判定（一步）

- 输入含企业名 → **单企调研（默认）**：直接出该企信息卡，不做候选池、不做评分。
- 输入含多家企业名 → **多企调研**：每家走 §2 快车道，并发采集，逐家各出一张卡、全部输出、不择优。
- 输入是产品/能力且明确要推荐 → **候选池推荐**：一轮召回 → top3 → 一次评分 → 出卡。

## 2. 单企调研（默认·快车道，≤5 次工具调用）

1. **一轮并发采集**：企业专有数据能力拉工商 / 主营 / 规模 / 风险；联网搜索只发 1 个合并词 `{企业名} 官网 电话 邮箱 主营 注册资本 成立` 补官网 / 联系方式 / 动态。
2. **核心字段缺才补 1 轮**：核心字段 = 注册资本 / 成立日期 / 主营业务。缺 → 定向补搜一次；官网 / 电话 / 邮箱缺 → 直接标「未检索到」，不补。
3. **标准化 + 出卡**：10 字段三态标注 → Final QA 2 问 → 调 `gate_final_qa` 一次 → 输出信息卡。

## 3. 候选池推荐（仅明确要求，一次评分）

1. **一轮召回**：只发 1-2 个合并关键词（产品 + 行业 + 区域），不逐通道搜索；候选 ≥3，红线一票否决（失信 / 破产 / 吊销 / 严重违法）。
2. **粗筛 top3**：按「产品匹配 + 触达可行性」一句话排序，取 top3。
3. **一轮采集**：top3 并发拉工商 / 主营；每企 1 个合并搜索词补官网 / 联系方式 / 动态。
4. **一次评分**：top3 一次性打完 8 维 → 调 `score_calculator` 一次 → 取综合分第 1。缺数据维度取中性分，不为评分补搜。
5. **出卡**：Final QA 4 问 → 调 `gate_final_qa` 一次 → 输出信息卡。

## 4. Final QA（一次过）

- **单企 2 问**：关键字段有来源或已显式降级？无编造、无矛盾？
- **候选池 4 问**：上述 2 问 + 评分每维有 basis？推荐 = 综合分第 1？
- 任一不通过：仅补搜一次或改写后重过；门禁脚本最多调用 2 次。

## 5. 输出纪律（红线）

- 可见 answer 只允许信息卡本体；候选池对比、评分明细、深挖、排除理由、Final QA 过程、工具名 / 脚本名 / 文档名 / 门禁名 / 能力名，**一律只进思考**。
- 字数 200~450（含标点），以可扫读、重点分明为准；缺项显式标「未检索到 / 推断」；禁止编造。
