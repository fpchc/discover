---
skill_id: client-finder
version: "1.6"
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
    when: 判定场景路由分支时
  - path: references/tier-funnel-prompts.md
    when: 阶段 1 需求澄清（三层漏斗追问）时
  - path: references/data-source-mapping.md
    when: 数据采集维度与数据能力映射
  - path: references/scoring-rules.md
    when: 八维评分子维度细则与权重
  - path: references/architecture.md
    when: 产业链层级推断与上下游定位
  - path: references/report-structure.md
    when: 报告结构与各 section 填充要求
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
workflow:
  workflow_id: client-finder
  phases:
    - phase_id: research
      executor: react
      goal: 场景判定、数据采集、候选评分与门禁校验
      inherit_tools: true
      fallback_phase: render
    - phase_id: render
      executor: render
      goal: 基于采集与评分结果生成完整 Markdown 客户发现报告
      allowed_tools: []
---
# 客户发现工作流

为电子信息产业链销售人员发现并评估潜在客户，最终交付一份完整 Markdown 文字报告。数据源由平台装配的数据能力提供，本技能只声明能力语义，不绑定具体服务。

## 执行主线

1. 场景判定与需求澄清：按 `references/scene-routing.md` 和 `references/tier-funnel-prompts.md` 确定目标。
2. 数据采集：按 `references/data-source-mapping.md` 采集工商、风险、财务与公开信息；优先企业专有数据能力，联网搜索仅兜底。
3. 候选池与评分：候选不足时扩展关键词；对候选按 `references/scoring-rules.md` 打八维子分，调用 `score_calculator` 计算综合分，禁止手算。
4. 报告交付：按 `references/report-structure.md` 组织完整 Markdown 报告，直接作为最终回复。

## 最终提交契约

- 完成后调用 `submit_final_answer`，`answer` 放完整 Markdown 报告正文。
- 数据缺口显式标注「未检索到」或「数据不充分·取中性分」，不静默编造。
- 评分必须经 `score_calculator`；红线或信用安全不达标的候选直接排除。
- 本阶段不调用 HTML 渲染，也不把内部工具名 / 脚本名 / 门禁名写入可见报告。
