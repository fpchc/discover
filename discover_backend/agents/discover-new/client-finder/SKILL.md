---
skill_id: client-finder
version: "3.4"
description: 客户调研——为销售调研潜在客户信息，候选池评分后推荐最优一家，输出 450~550 字信息卡
scope:
  applies: 销售调研客户信息、从候选池推荐最优客户、售前情报收集时
  does_not_apply: 需要完整八维长篇客户发现报告、非电子信息产业链调研的通用咨询、纯闲聊
keywords: [客户调研, 调研客户, 客户信息, 最优客户, 推荐客户, 工商信息, 主营业务, 销售情报]
capability_dependencies:
  - capability: enterprise_business
    core_tools: [search_companies, get_company_basic_profile]
    required: false
  - capability: enterprise_risk
    core_tools: []
    required: false
  - capability: web_search
    core_tools: [web_search_tencent]
    required: true
scripts:
  - path: scripts/score_calculator.py
    name: score_calculator
    description: 八维量化评分计算器（含 Score Trace）。仅候选池场景使用，评分必须经此脚本
    schema_path: schemas/score_input.json
documents:
  - path: references/card-format.md
    when: 输出企业信息卡正文时（三段式结构、加粗要点、正反例，排版唯一权威）
    preload: true
  - path: references/evidence-rules.md
    when: 证据等级判定、缺项是否补搜时
    preload: true
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
workflow:
  workflow_id: client-finder
  phases:
    - phase_id: research
      executor: react
      goal: 采集候选企业工商、规模、触达与风险信息
      inherit_tools: true
      fallback_phase: render
    - phase_id: render
      executor: render
      goal: 基于已采集信息生成 450~550 字信息卡正文
      allowed_tools: []
---
# 客户调研工作流

交付物：单企为一张 450~550 字信息卡；多企输入时每家各出一张 450~550 字信息卡并全部输出，禁止合并成一张总体卡。排版强制三段式，细节以 `references/card-format.md` 为准。

## 场景判定

- 输入含企业名 → 单企调研，直接出卡，不评分。
- 输入含多家企业名 → 多企调研，每家独立采集并各出一张卡、全部输出、不择优。
- 输入是产品/能力且明确要推荐 → 候选池推荐：一轮召回 → top3 → 一次评分 → 出卡。

## 数据采集

- 优先使用企业工商能力与企业风险能力；缺失或未覆盖的字段再用联网搜索能力兜底。
- 单企快车道：一轮并发采集；仅注册资本 / 成立日期 / 主营业务缺失时定向补搜一轮。
- 官网 / 电话 / 邮箱缺失直接标「未检索到」，不额外补搜。
- 候选池仅对 top3 一次性评分；缺数据维度取中性分，不为评分补搜。

## 最终提交契约

- 完成后调用 `submit_final_answer`，`answer` 只放信息卡正文。
- 多企输入时逐卡拼接，每张卡独立满足 450~550 字。
- 最终提交前调用 `gate_final_qa` 门禁脚本一次；失败只修复一次后重新提交。
- 可见 answer 不得出现候选池对比、评分明细、排除理由、Final QA 过程、工具名 / 脚本名 / 文档名 / 门禁名 / 能力名。
