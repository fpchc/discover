# ReAct Agent 优化方案

> **文档性质**：架构优化设计方案
> **创建日期**：2026-09-02
> **核心目标**：解决 ReAct 死循环问题

---

## 一、核心问题分析

### 1.1 ReAct 的死循环本质

**问题根源**：控制权完全交给 LLM，由概率模型决定"继续"还是"停止"

**三种典型场景**：

1. **自我怀疑循环**
   - LLM 认为"信息可能不够准确"
   - 反复执行相同查询
   - 永远无法确认"足够准确"

2. **状态震荡**
   - 状态 A 需要状态 B 的结果
   - 状态 B 又需要状态 A 的结果
   - A → B → A → B 无限循环

3. **永远的 80%**
   - LLM 认为"再补充一点就完美了"
   - 不断追求完美
   - 永远达不到 100%

### 1.2 当前架构现状

**现有结构**：
```
Runtime (engine.py)
├── LangGraph 状态图
├── GraphState (state.py)
├── 节点：resolve → assemble → think → execute_tools
└── 工具调用链路
```

**存在的问题**：
- ❌ 无死循环防护（`turn` 仅在单消息内重置）
- ❌ 无状态震荡检测
- ❌ 无动作重复检测
- ❌ 无成本预算控制
- ⚠️ LLM 完全控制流程，无确定性规则验证

**优势**：
- ✅ LangGraph 状态管理完善
- ✅ 工具调用链路清晰
- ✅ 事件流可观测性好

---

## 二、解决方案设计

### 2.1 核心理念：控制反转

```
传统 ReAct：
    LLM 决定 → 执行 → LLM 决定是否继续 → 循环
    ❌ 控制权在 LLM，不确定性高

控制反转方案：
    Engine 检查 → LLM 建议 → Engine 验证 → 执行 → Engine 判断继续/停止
    ✅ 控制权在 Engine，确定性高
```

### 2.2 架构设计：包装层模式

**设计原则**：
- 最小侵入，不修改现有 Runtime 核心逻辑
- 不改动 LangGraph 状态图
- 可配置开关，易于回滚

**架构图**：
```
┌─────────────────────────────────────┐
│   GuardedRuntime (新增包装层)       │
│   ├── Pre-Turn Guards               │
│   │   ├── Iteration Guard           │
│   │   ├── Oscillation Guard         │
│   │   └── Cost Guard                │
│   ├── Post-Turn Guards              │
│   │   └── Repetition Guard          │
│   └── State History Tracking        │
└──────────────┬──────────────────────┘
               │ 委托
┌──────────────▼──────────────────────┐
│   Runtime (现有，不修改)             │
│   ├── run_turn()                    │
│   ├── LangGraph                     │
│   └── think / execute_tools         │
└─────────────────────────────────────┘
```

### 2.3 四层 Guard 系统

| Guard | 作用 | 检查点 | 阈值示例 |
|-------|------|--------|---------|
| **Iteration Guard** | 防止无限循环 | Pre-turn | 累积轮次 ≥ 30 |
| **Oscillation Guard** | 防止状态震荡 | Pre-turn | 检测 A-B-A-B 模式 |
| **Repetition Guard** | 防止工具重复调用 | Post-turn | 连续 3 次相同调用 |
| **Cost Guard** | 防止成本超支 | Pre-turn | Token 使用量 ≥ 预算 |

**检查流程**：
```
每轮执行前：
  1. Iteration Guard 检查累积轮次
  2. Oscillation Guard 检查状态历史
  3. Cost Guard 检查 Token 使用量
  → 任一阻止 → 返回部分结果并终止

执行 Runtime.run_turn()

每轮执行后：
  1. Repetition Guard 检查动作历史
  2. 记录状态历史（用于下轮检查）
  3. 更新累积计数
  → 阻止 → 标记警告并终止
```

### 2.4 状态震荡检测算法

**核心思想**：检测状态历史中的循环模式

**检测策略**：
1. **简单循环**：A-B-A-B-A-B（长度 2，重复 3 次）
2. **复杂循环**：A-B-C-A-B-C-A-B-C（长度 3，重复 3 次）
3. **可扩展**：支持检测任意长度的循环

**判断逻辑**：
- 提取最近 N 步状态历史（滑动窗口）
- 遍历可能的循环长度（2 到 N/3）
- 检查是否存在连续 3 次重复的模式

---

## 三、数据结构设计

### 3.1 扩展 GraphState

**新增字段**（保持向后兼容）：
```python
class GraphState(BaseModel):
    # 现有字段保持不变
    # ...

    # 新增：Guard 系统字段
    state_history: list[str]        # 状态转换历史（最近 20 条）
    action_history: list[dict]      # 动作历史（最近 20 条）
    cumulative_turns: int           # 累积推理轮次
```

**兼容性处理**：
- 现有会话的 `last_state` 没有新字段 → 初始化为默认值
- 使用 `list` 而非 `deque`，确保 Pydantic 序列化兼容
- 在 GuardedRuntime 中手动维护滑动窗口（保留最近 20 条）

### 3.2 Guard 结果模型

```python
class GuardResult:
    blocked: bool               # 是否阻止
    reason: str                 # 阻止原因
    severity: "info|warning|error"  # 严重程度
```

---

## 四、集成方案

### 4.1 GuardedRuntime 包装层

**职责**：
- 持有现有 Runtime 实例
- 初始化 4 个 Guard
- 包装 `run_turn()` 方法
- 在执行前后插入 Guard 检查
- 维护状态历史和动作历史

**核心流程**：
```
async def run_turn(...):
    1. 获取上一轮状态 (last_state)

    2. Pre-turn Guards 检查
       - 任一阻止 → 返回终止状态（含部分结果）

    3. 委托给 Runtime.run_turn() 执行

    4. Post-turn Guards 检查
       - 阻止 → 添加系统提示并标记终止

    5. 更新累积计数和历史记录
       - cumulative_turns += turn
       - state_history.append(active_skill)
       - action_history.append(tool_calls)
       - 维护滑动窗口（保留最近 20 条）

    6. 返回结果状态
```

### 4.2 依赖注入集成

**修改点**：
- `app/interfaces/http/deps.py`：创建 GuardedRuntime 替代 Runtime
- `app/interfaces/http/chat.py`：依赖注入使用 GuardedRuntime

**配置化**：
```python
# .env
AGENT_ENABLE_GUARDS=true        # 是否启用 Guard（开关）
AGENT_MAX_TURNS=30              # 最大推理轮次
AGENT_TOKEN_BUDGET=100000       # Token 预算l
AGENT_MAX_ACTION_REPEATS=3      # 最大动作重复次数
```

---

## 五、实施路线

### Phase 1: 核心 Guard 系统（2-3 天）

**目标**：实现四层 Guard + 包装层

**交付物**：
- [ ] `app/runtime/guards/` 模块
  - [ ] `base.py` - Guard 基类和 GuardResult
  - [ ] `iteration.py` - Iteration Guard
  - [ ] `oscillation.py` - Oscillation Guard（核心算法）
  - [ ] `repetition.py` - Repetition Guard
  - [ ] `cost.py` - Cost Guard
- [ ] `app/runtime/guarded_engine.py` - GuardedRuntime 包装层
- [ ] 单元测试：每个 Guard 的阻止/通过条件

**验收标准**：
```bash
pytest tests/unit/guards/ -v --cov=app.runtime.guards
# 覆盖率 >= 90%
```

---

### Phase 2: 集成到现有架构（1 天）

**目标**：集成 GuardedRuntime 到依赖注入

**交付物**：
- [ ] 扩展 `GraphState`（新增 3 个字段）
- [ ] 修改 `deps.py`（创建 GuardedRuntime）
- [ ] 增加配置项到 `Settings`
- [ ] 更新 `.env.example`

**验收标准**：
- 启动服务无报错
- 配置开关生效（`AGENT_ENABLE_GUARDS=false` 可回退）

---

### Phase 3: 集成测试（1 天）

**目标**：验证防护有效性

**测试场景**：
- [ ] 正常对话场景（Guard 不阻止）
- [ ] 超时场景（触发 Iteration Guard）
- [ ] 循环场景（触发 Oscillation Guard）
- [ ] 重复调用场景（触发 Repetition Guard）
- [ ] 成本超支场景（触发 Cost Guard）

**验收标准**：
```bash
pytest tests/integration/test_guarded_runtime.py -v
# 所有场景通过
```

---

## 六、优势与风险

### 6.1 核心优势

| 维度 | 原架构 | 优化后 |
|------|--------|--------|
| 死循环防护 | ❌ 无 | ✅ 四层 Guard |
| 状态震荡检测 | ❌ 无 | ✅ 改进算法（检测复杂循环）|
| 工具重复调用 | ❌ 无控制 | ✅ Repetition Guard |
| 成本控制 | ⚠️ 仅统计 | ✅ 预算检查 + 阻止 |
| 优雅降级 | ❌ 硬中断 | ✅ 返回部分结果 |
| 侵入性 | - | ✅ 包装层，不改核心 |
| 可回滚 | - | ✅ 配置关闭即可 |

### 6.2 潜在风险与缓解

**风险 1：兼容性问题**
- 风险：现有会话的 `last_state` 没有新字段
- 缓解：在 GuardedRuntime 中检查字段是否存在，不存在则初始化

**风险 2：误判**
- 风险：某些复杂任务可能需要超过 30 轮或多次调用同一工具
- 缓解：提供配置项调整阈值；支持按 Skill 类型动态调整

**风险 3：性能影响**
- 风险：每轮执行前后的 Guard 检查可能影响性能
- 缓解：所有 Guard 检查都是 O(1) 或 O(n)（n ≤ 20），影响极小

---

## 七、后续优化方向

### 7.1 Phase Contract（可选）

在特定阶段检查数据质量：
- 在关键状态节点后验证数据完整性
- 提前发现数据质量问题
- 避免基于错误数据继续执行

### 7.2 自适应预算（可选）

根据对话复杂度动态调整预算：
- 简单对话：预算 20k tokens
- 复杂分析：预算 100k tokens
- 基于历史数据学习预估

### 7.3 前端可视化（可选）

在前端展示 Guard 状态：
- 当前累积轮次 / 最大轮次
- 接近阈值时的预警提示
- Guard 阻止时的友好提示

### 7.4 智能放宽策略（可选）

某些场景下动态放宽限制：
- 用户明确要求"详细分析"时增加轮次限制
- 根据 Skill 类型调整阈值（研究型 vs 查询型）
- 基于历史成功率动态调整

---

## 八、关键设计决策

### 8.1 为什么用包装层而非直接修改 Runtime？

**优势**：
- 最小侵入，降低风险
- 易于回滚（配置开关）
- 便于测试和迭代
- 不影响现有 Runtime 的稳定性

### 8.2 为什么用 list 而非 deque？

**原因**：
- Pydantic 序列化兼容性
- GraphState 需要跨边界传递
- deque 不能直接序列化为 JSON

**解决方案**：
- 使用 list 存储
- 在 GuardedRuntime 中手动维护滑动窗口（保留最近 20 条）

### 8.3 为什么检测"连续 3 次重复"？

**依据**：
- 1 次重复：可能是正常重试
- 2 次重复：可能是多次确认
- 3 次重复：大概率是死循环

**可调整**：
- 可配置为 2 次或 4 次
- 可根据工具类型区别对待

---

## 九、总结

### 核心思想
- **控制反转**：将控制权从 LLM 转移到 Engine
- **包装层模式**：最小侵入，易于回滚
- **多层防护**：四个维度的独立检查
- **优雅降级**：返回部分结果而非硬中断

### 实施周期
- **Phase 1**：2-3 天（核心 Guard 系统）
- **Phase 2**：1 天（集成到架构）
- **Phase 3**：1 天（集成测试）
- **总计**：4-5 天

### 优先级
- **P0（必须）**：Iteration Guard + Oscillation Guard
- **P1（重要）**：Cost Guard + Repetition Guard
- **P2（可选）**：Phase Contract + 自适应预算

---

**文档结束**
