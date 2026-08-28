---
skill_id: client-finder
version: "2.0"
description: 客户调研——为销售调研潜在客户信息，候选池评分后推荐最优一家，输出 300 字以内信息卡
scope:
  applies: 销售调研客户信息、从候选池推荐最优客户、售前情报收集时
  does_not_apply: 需要完整八维长篇客户发现报告、非电子信息产业链调研的通用咨询、纯闲聊
keywords: [客户调研, 调研客户, 客户信息, 最优客户, 推荐客户, 工商信息, 主营业务, 销售情报]
capability_dependencies:
  - capability: web_search
    core_tools: []
    required: true
    degrade_note: null
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
documents:
  - path: references/scene-routing.md
    when: 判定七类场景路由分支时
  - path: references/tier-funnel-prompts.md
    when: 阶段 1 需求澄清（三层漏斗追问）时
  - path: references/data-source-mapping.md
    when: 数据采集维度与降级策略，P1 仅平台联网搜索（web_search 能力）
  - path: references/scoring-rules.md
    when: 八维评分子维度细则与权重
  - path: references/architecture.md
    when: 产业链层级推断与上下游定位（用于判断最优候选）
gates:
  - id: candidate_pool
    condition: 候选池 ≥ 5 家（P1 数据受限，不足时向用户说明并继续）
    blocking: false
  - id: score_valid
    condition: 每客户 8 维子分均非 0 且 score_calculator 输出有效
    blocking: false
---
# 客户调研工作流（P1 数据受限版）

## 0. 定位与场景

为销售人员调研潜在客户信息。七大类场景（核心拓客 / 定向搜索 / 持续跟进 / 单企评估 / 竞品反推 / 机会扫描 / 区域聚焦）**合并为本技能内的路由分支**，由场景判定规则分支，不拆成多个技能。场景判定见 `references/scene-routing.md`。

**最终交付**：从候选池中推荐综合分最优的一家，可见输出一份 300 字以内的客户信息卡；其余分析全部放思考。

## 1. 阶段 0：会话感知（去重）

1. 用 `dedup_manager`（mode=exclude）读取历史推荐，输入产品关键词 + 目标行业。
2. 返回相似线索（相似度≥0.7）→ 向用户给出 A/B/C（激活后备池 / 全新搜索 / 刷新推荐）；无匹配则直接进阶段 1。
3. 历史已推荐企业自动进入排除列表；用户排除条件一并生效。

## 2. 阶段 1：需求澄清（三层漏斗追问）

唯一人机交互窗口，话术见 `references/tier-funnel-prompts.md`。
- 第一层（必问）：产品/能力描述，信息不足必须追问。
- 第二层（默认）：应用场景 / 差异化优势 / 标杆客户 / 竞品，可说「跳过」。
- 第三层（按需）：目标行业 / 区域 / 规模 / 排除 / 节奏（输出固定为最优一家），缺省用默认值。
- 完成需求总结确认后再进入阶段 2。

## 3. 阶段 2：搜索 → 初筛 → 评分

### 3.1 搜索与初筛（数据受限）
P1 数据源仅平台联网搜索（`web_search` 能力，具体提供方由平台配置）。多路关键词并发：产品名+行业、行业+区域、竞品+客户/供应链、招标/机会词。
- 候选池不足 5 家 → 扩展关键词 / 放宽区域重搜；仍不足则明确告知用户。
- 初筛：仅凭公开信息判断，信用红线一票否决（失信 / 破产 / 吊销 / 严重违法）直接排除；其余入深挖队列或后备池。
- 排除过滤器生效。

### 3.2 深挖（尽力而为 + 显式标注）
对深挖队列逐企采集公开信息，维度：① 工商速览（注册资本/成立日期/地址/企业规模/电话/邮箱/官网）② 主营与产品 ③ 采购规模线索（扩产/招聘/招标）④ 动态信号（须带日期，超 6 个月标注「可能已过时」）⑤ 风险 ⑥ 产业链定位（`references/architecture.md`）。
- 应尽可能批量并发搜索，覆盖多维度；P1 无硬性最低调用数。
- 事实断言（技术来源 / 份额 / 客户关系 / 竞品对比）须 ≥2 独立来源；单源断言必须标注来源；推断用限定词。

### 3.3 八维评分（强制计算器）
1. 按 `references/scoring-rules.md` 逐维打子分（0-10），记录依据与来源。
2. 写临时 JSON → 调用 `score_calculator`（**必须经脚本，禁止 AI 直接给综合分**）。
3. 输出写回：综合分 / 排名 / 8 维子分。数据缺失维度取中性分并标注「数据不充分·取中性分」。
4. 信用安全 < 3.0 或触发红线 → 直接排除。
- 评分全过程在思考中完成，不进可见回答。

### 3.4 门禁
- `candidate_pool` 候选池 ≥ 5 家：尽力，不足向用户说明。—— 警告级
- `score_valid` 每客户 8 维子分非空且计算器输出有效。—— 警告级

## 4. 阶段 3：推荐最优客户，输出 300 字信息卡

1. 从候选池按综合分取**最优一家**；并列时参考采购规模、触达可行性、产业链卡位（`references/architecture.md`）决出唯一推荐。
2. 可见 `answer` 输出一份 ≤300 字的客户信息卡，仅含三部分：
   - **一句话定位**：行业，产品，营收规模，是否上市
   - **工商信息**：注册资本，成立日期，地址，企业规模，联系电话，邮箱，官网
   - **主营业务**
3. **思考规范（核心）**：候选池全貌、各家对比、评分明细与依据、深挖细节、排除理由——全部在 **thinking（思考过程）** 中完成，**严禁**写入可见 `answer`。可见输出只有上述信息卡。
4. 数据缺口显式标注「未检索到」，不静默编造；信息卡正文不超过 300 字。

## 5. 执行纪律

- 先澄清再搜索，不跳过第一层必问。
- 评分必须走 `score_calculator`，禁止手算综合分。
- 可见输出仅 300 字信息卡；分析一律进思考，不泄入可见回答。
- 尽力采集 + 显式标注，绝不对数据缺口静默编造。
