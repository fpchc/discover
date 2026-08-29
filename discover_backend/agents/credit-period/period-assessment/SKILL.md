---
skill_id: period-assessment
version: "1.0"
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
  - path: scripts/gate_report_valid.py
    name: gate_report_valid
    description: 账期评估报告结构校验器——章节完整性/占位符残留/评分一致性，失败项结构化返回
    schema_path: schemas/gate_input.json
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
---
# 账期评估工作流（P1 数据受限版）

## 0. 定位与场景

为销售与财务人员评估**单个客户**的可授信账期与额度。输入 1 家客户名称 → 输出完整账期评估文字报告。

核心回答：「给这家客户放 N 天账期、M 元额度，回款风险多大」。决策由四层事实决定：

| 层次 | 回答的问题 | 数据能力（平台装配） |
|------|-----------|----------|
| L1 资质真伪 | 公司真实、在营、规模多大？ | 企业画像能力（enterprise_business） |
| L2 偿付能力 | 有没有钱还、赚不赚钱？ | 财务数据能力（financial_data，上市）；非上市标注受限 |
| L3 偿付意愿 | 过去拖不拖款？ | 企业风险能力（enterprise_risk） |
| L4 账期内风险 | 会不会爆雷？ | 企业风险能力（enterprise_risk） + 联网搜索（web_search） |

## 1. 阶段 0：需求澄清（实体锚定 + 客户类型判定）

唯一人机交互窗口。
1. **实体锚定（必做）**：用企业画像数据能力（enterprise_business）查询客户完整登记名，消除简称歧义；多候选时由用户选择，禁止 AI 自动选第一条。
2. **客户类型判定（必做）**：按 `references/scoring-rules.md` 判定 T1-T4（上市/营收规模/成立年限/贸易型）。
3. **关注点确认（可选）**：默认全面评估；用户可说「开始吧」跳过。

## 2. 阶段 1：数据采集（尽力采集 + 显式标注）

按 `references/data-source-mapping.md` 的维度映射采集；数据能力由平台装配（企业专有数据 + 联网搜索，可用工具以运行时目录为准）。采集维度：
① 工商速览（注册资本/成立日期/地址/规模/经营状态）② 财务（上市：公开财报；非上市：标注受限）③ 信用风险（失信/被执行/欠税/票据违约）④ 经营稳定性（经营异常/股权冻结/行政处罚/涉诉）⑤ 需求盘子（营收规模/采购线索）⑥ 付款习惯与舆情。

- 事实断言（财务数字/涉诉/处罚）须 ≥2 独立来源或标注单源；推断用限定词。
- 关键数据双源偏差按 `references/cross-validation-rules.md` 四级协议处理（通过/偏差取保守值/单源标注/阻塞级中止）。
- 找不到的信息显式标注「未检索到」，不静默编造。

## 3. 阶段 2：F/R/S 评分（强制计算器）

1. 按 `references/scoring-rules.md` 逐维打 F/R/S 子分（F 0-10 / R 0-10 / S 0-10），记录依据与来源；数据缺失子维度取中性分并标注。
2. 写临时 JSON → 调用 `period_calculator`（**必须经脚本，禁止 AI 直接给综合分**）。
3. 输出写回：综合授信分 / 授信等级 / 建议账期 / 建议额度。
4. **红线门禁**（`references/scoring-rules.md` 六节）：任一触发 → 阻断，不进入评分，报告输出「现款现货/30%预付」。
5. 非上市客户（T2/T3/T4）财务子维度强制中性分（`references/scoring-rules.md` 二节）。

## 4. 阶段 3：完整文字报告交付

按以下结构输出**完整 Markdown 文字报告**作为最终回复；不生成 HTML、不调用渲染脚本。

1. **封面信息**：委托方、评估客户、评估日期、数据来源受限说明（P1 公开搜索）。
2. **授信结论（导读）**：F/R/S 评分与权重、综合授信分、授信等级、建议账期、建议额度、一句话结论。
3. **客户基本面**：工商速览（注册资本/成立日期/地址/规模/经营状态）。
4. **财务健康（F）**：各子维度明细与依据；非上市标注「财报不可得·取中性分」。
5. **信用风险（R）**：失信/被执行/欠税/票据违约/涉诉明细，区分原告与被告。
6. **经营稳定性（S）**：经营异常/股权冻结/行政处罚/涉诉明细。
7. **需求盘子与额度测算**：年盘子估算（给区间不给单点）→ 额度公式 → 敏感性。
8. **风险信号与红线状态**：5 条红线逐条判定；风险信号矩阵。
9. **监控与复盘方案**：监控指标、退出触发、季度滚动评估建议。
10. **附录**：数据采集日志（工具来源）、评分方法论、对抗式审查记录、免责声明。

报告交付前通过 `gate_report_valid` 校验（`report_structure` 门禁）。

## 5. 门禁

- `redline_clear`：5 条红线全未触发，否则阻断。—— 阻断级
- `score_valid`：子分非空且 `period_calculator` 输出有效。—— 警告级
- `report_structure`：`gate_report_valid` 校验通过（章节完整/无占位符/评分一致）。—— 阻断级

## 6. 执行纪律

- 先澄清再采集，实体锚定必做，禁止跳过第一层。
- 评分必须走 `period_calculator`，禁止手算综合分。
- 红线触发即阻断，不进入评分，不尝试「酌情放宽」。
- 数据缺口显式标注「未检索到」/「数据不充分·取中性分」，不静默编造。
