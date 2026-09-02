---
skill_id: client-finder
version: "3.0"
description: 客户调研——为销售调研潜在客户信息，候选池评分后推荐最优一家，输出 300 字以内信息卡
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
    description: 八维量化评分计算器（含 Score Trace）。评分必须经此脚本，禁止直接给综合分
    schema_path: schemas/score_input.json
documents:
  - path: references/scene-routing.md
    when: 判定场景与搜索策略时
  - path: references/scoring-rules.md
    when: 八维评分子维度细则与权重
  - path: references/evidence-rules.md
    when: 证据等级判定、交叉验证、动态补搜
  - path: references/architecture.md
    when: 产业链层级推断与上下游定位（判断最优候选）
gates:
  - id: candidate_pool
    condition: 候选池 ≥ 5 家（数据受限不足时向用户说明并继续）
    blocking: false
  - id: score_valid
    condition: 每客户 8 维子分均非 0 且 score_calculator 输出有效（含 trace）
    blocking: false
  - id: final_qa
    condition: Final QA 六问全部通过，任一不通过先补搜再重过
    validator: scripts/gate_final_qa.py
    schema_path: schemas/final_qa_input.json
    blocking: true
---
# 客户调研工作流（V3 准确性优先版）

最终交付：单企调研直接出该企信息卡；候选池推荐则出综合分最优的一家。可见输出始终是一份 300 字以内的客户信息卡；其余分析全部放思考。

## 流水线

```
需求 → 场景识别 → 分流
   ├─ 单企调研（输入企业名，快车道）：并发采集该企 10 字段 → 缺项定向补搜 → 字段标准化 → Final QA → 300 字卡
   └─ 候选池推荐（输入产品/能力，完整流水线）：澄清(动态追问) → 多通道召回(6通道) → 候选池≥5 → 粗筛 top3
        → 数据采集 → 证据验证 → 动态补搜 → 字段标准化
        → 八维评分(top3,子维锚点) → 红线/信用 → Score Trace → Final QA → 300 字卡
```

## 1. 场景识别（先分流，再执行）

按 `references/scene-routing.md` 判定场景。两种基本形态走**两条不同长度的路径**：

- **输入企业名 → 单企调研（快车道）**：跳过候选池召回、八维评分、Score Trace 三步，
  直接「并发采集该企 10 字段 → 缺项定向补搜 → 字段标准化 → Final QA → 出卡」。
  单企无比较对象，八维评分不产生额外信息，故整体跳过。
- **输入产品/能力 → 候选池推荐（完整流水线）**：走召回 → 粗筛 top3 → 评分 → 出卡。

## 2. 澄清（动态追问，仅候选池场景）

- 单企调研已给出企业名，跳过本步直接采集。
- 第一层必问：卖什么产品 / 调研哪家公司。信息不足必须追问。
- 其余条件（目标行业 / 区域 / 规模 / 排除 / 节奏）批量一次问，可「跳过 / 默认」。
- 答案含糊时动态追一档（如「连接器」→「什么类型？用在哪？」），不因合并轮次牺牲信息质量。
- 完成需求总结确认后再进入召回。

## 3. 多通道召回（6 通道，候选池 ≥5）

多路关键词**并发**：产品+行业、行业+区域、竞品+客户/供应链、招标/机会词、行业+区域+规模、产品+区域——同一轮一次发出，不串行。
- 候选池不足 5 家 → 扩展关键词 / 放宽区域重搜；仍不足则向用户说明。
- 初筛红线一票否决（失信 / 破产 / 吊销 / 严重违法）直接排除，不入深挖。
- **粗筛 top3**：召回后用两个高区分度维度（产品匹配 + 触达可行性）快速排序，只保留 top3 进入逐企采集与八维评分，其余候选不再深挖；边界分接近时保留 4 家，避免误杀明显赢家。

## 4. 采集 + 证据验证 + 动态补搜

逐企采集 10 字段 + 8 维所需信号，按 `references/evidence-rules.md` 判定证据等级与独立性。
- **并发**：多家候选的采集同一轮并发发出（企业专有能力 + 联网搜索仅兜底），不逐家串行。
- **合并搜索词**：每企首轮 1-2 个合并搜索词覆盖多字段（见 evidence-rules §四），减少搜索轮次；仅对首轮后仍缺关键证据的字段定向补搜，停止条件 = 达标或通道穷尽。

## 5. 字段标准化

把采集结果统一到 10 字段，每字段标三态：有来源 / 推断 / 未检索到。

## 6. 八维评分（强制走脚本，仅候选池场景）

> 单企调研**跳过**本步与 §7，直接进 §8 Final QA。

1. 仅对 §3 粗筛出的 **top3** 逐维打子分（0-10），每维记录依据(basis)与来源(source)；top3 之外不评分。
2. 写临时 JSON → 调 `score_calculator`（**必须经脚本，禁止 AI 直接给综合分**）。
3. 数据缺失维度取中性分并标注「数据不充分·取中性分」。
4. 信用安全 < 3.0 或触发红线 → 直接排除。

## 7. Score Trace（仅候选池场景）

`score_calculator` 输出含每维 basis / source，最终综合分可反推每一维依据。单企调研无评分，本步跳过。

## 8. Final QA（输出前强制，阻断级）

六问自检，任一不通过先补搜再重过。**单企调研只做 1-3 问**（无评分与排名），候选池推荐做全部六问：
1. **证据充分？** 关键字段有 ≥2 独立达标证据，或已显式降级
2. **字段准确？** 无编造、无矛盾
3. **有无冲突？** 不同来源信息矛盾未解决
4. **评分与证据一致？** 每维分数有 basis 支撑
5. **排名与评分一致？** 推荐 = 综合分第 1
6. **推荐理由有证据？** 推荐结论可追溯到证据

六问通过后，**必须调用 `gate_final_qa` 脚本**（入参 `answer` = 信息卡正文）校验可见回答无泄露：脚本返回 `passed=false` 时，按 `errors` 提示删除内部机制名后重写，再次调用直至 `passed=true`。

## 9. 输出 300 字卡

按 AGENT.md 输出契约输出；并列时参考采购规模、触达可行性、产业链卡位决出唯一推荐。

**可见 answer 只允许信息卡本体，其余一律只进 thinking**：候选池对比、评分明细、深挖、排除理由、Final QA 六问的结果与过程、任何工具名/脚本名/文档名/门禁名/能力名，**严禁**写入可见回答。发现正文混入上述内容立即删掉，只保留信息卡。
