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
  - id: render_pass
    condition: 报告必备章节齐全（评分 / 决策人 / 切入 / 风险）、无占位符、无工具名泄露
    validator: scripts/gate_render_valid.py
    schema_path: schemas/gate_input.json
    blocking: true
workflow:
  workflow_id: client-finder
  output_contract_refs:
    - render_pass
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
      input_bindings:
        research.report_data: report_data
---
# 客户发现工作流

为电子信息产业链销售人员发现并评估潜在客户，最终交付一份完整 Markdown 文字报告。数据源由平台装配的数据能力提供，本技能只声明能力语义，不绑定具体服务。

## 工作约束

- 评分必须经 `score_calculator`，禁止手算；红线或信用安全不达标的候选直接排除。
- 质量自检（非硬门禁）：候选池尽量 ≥ 5 家（P1 数据受限时向用户说明并继续）；每客户 8 维子分均非 0 且 `score_calculator` 输出有效。

## 阶段协作与最终提交契约

- research 阶段结束用 `complete_phase`，`output.report_data` 携带已采集/评分结果，供 render 阶段确定性读取。
- render 阶段由平台确定性收尾，生成完整 Markdown 客户发现报告，不调用工具。
- render 完成后平台执行 `gate_render_pass` 门禁（章节齐全/无占位符/无泄露全部阻断级）；失败只修复一次后重跑。
- 数据缺口显式标注「未检索到」或「数据不充分·取中性分」，不静默编造。
- 不把内部工具名 / 脚本名 / 门禁名写入可见报告。
