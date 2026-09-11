---
skill_id: period-assessment
version: "1.1"
description: 账期评估——单客户 F/R/S 三因子量化评分，输出建议账期/建议额度/授信等级与完整账期评估文字报告
scope:
  applies: 评估单客户账期与授信额度、放账期决策、客户付款风险评估、客户尽调时
  does_not_apply: 多客户横向对比、与企业信用无关的通用咨询、纯闲聊
keywords: [账期, 授信, 放账期, 信用额度, 账期评估, 客户评估, 付款风险, 给多少账期, 客户尽调, 回款风险]
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
  - path: scripts/period_calculator.py
    name: period_calculator
    description: F/R/S 三因子加权评分计算器，输出综合授信分/授信等级/建议账期/建议额度。评分必须经此脚本，禁止 AI 手算综合分
    schema_path: schemas/period_input.json
documents:
  - path: references/data-source-mapping.md
    when: 数据采集维度与数据能力映射
  - path: references/scoring-rules.md
    when: F/R/S 评分子维度细则、T1-T4 分层权重、红线门禁判定
  - path: references/period-rules.md
    when: 账期档位硬约束、额度计算、需求盘子估算
  - path: references/cross-validation-rules.md
    when: 关键数据双源验证与偏差处理（四级偏差协议）
  - path: references/adversarial-checklist.md
    when: 报告交付前过 8 条对抗式审查（灵魂拷问）
  - path: references/credit-period.json
    when: 需要参考完整账期评估示例输出（数据与报告结构、gate_report_valid 入参结构）时
gates:
  - id: redline_clear
    condition: 5 条红线全未触发；任一触发则输出「阻断·现款现货/30%预付」，不进入评分
    blocking: true
  - id: score_valid
    condition: 每客户 F/R/S 子分非空且 period_calculator 输出有效
    blocking: false
  - id: report_structure
    condition: 报告章节完整、无占位符残留、评分与 period_calculator 输出一致
    validator: scripts/gate_report_valid.py
    schema_path: schemas/gate_input.json
    blocking: true
workflow:
  workflow_id: period-assessment
  phases:
    - phase_id: research
      executor: react
      goal: 实体锚定、数据采集、F/R/S 评分与门禁校验
      inherit_tools: true
      fallback_phase: render
    - phase_id: render
      executor: render
      goal: 基于采集与评分结果生成完整 Markdown 账期评估报告
      allowed_tools: []
---
# 账期评估工作流

为销售与财务人员评估单个客户的可授信账期与额度，最终交付完整 Markdown 文字报告。核心回答：「给这家客户放 N 天账期、M 元额度，回款风险多大」。

## 执行主线

1. 实体锚定：使用企业工商能力解析完整登记名，多候选时由用户选择，禁止自动选第一条。
2. 数据采集：按 `references/data-source-mapping.md` 采集工商、财务、风险、经营稳定性与需求盘子；优先企业专有数据能力，联网搜索仅兜底。
3. 评分：按 `references/scoring-rules.md` 打 F/R/S 子分，调用 `period_calculator` 计算综合授信分、等级、建议账期与额度；红线触发即阻断。
4. 报告交付：按 `references/period-rules.md`、`references/cross-validation-rules.md` 与 `references/adversarial-checklist.md` 组织并自检报告。

## 最终提交契约

- 完成后调用 `submit_final_answer`，`answer` 放完整 Markdown 报告正文。
- 报告提交前调用 `gate_report_structure` 门禁脚本；失败按结构化错误修复后重跑。
- 红线触发时报告结论为「阻断·现款现货/30%预付」，不进入评分。
- 数据缺口显式标注「未检索到」或「数据不充分·取中性分」，不静默编造。
