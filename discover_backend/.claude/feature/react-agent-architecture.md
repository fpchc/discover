# ReAct Agent 架构优化方案

> **文档性质**：现有架构的增强优化方案  
> **创建日期**：2026-09-02  
> **状态**：设计方案，待实施  
> **核心目标**：解决 ReAct 死循环问题，增强控制能力

---

## 一、核心问题与解决思路

### 1.1 ReAct 的根本问题

**典型死循环场景**：

```python
# 场景1：LLM 自我怀疑循环
Action: search("华为")
Observation: "找到：华为技术有限公司..."
Thought: "信息可能不够准确，我再确认一次"
Action: search("华为")  # 无限循环

# 场景2：状态震荡
analyze_product() → "需要公司背景"
get_company_info() → "需要先分析产品"
# A → B → A → B 无限震荡

# 场景3：永远达不到的完美
Thought: "信息收集了80%，还需要补充"
Action: search_supplement()
# 永远到不了100%
```

**根本缺陷**：
- 控制权在 LLM，由概率模型决定"继续"还是"停止"
- 无确定性保障，LLM 可能永远认为"还差一点点"
- 状态不可控，容易陷入状态震荡或无效重复

### 1.2 解决方案

**核心理念：控制反转**

```
❌ 传统 ReAct：LLM 完全控制 → 死循环风险
✅ 控制反转：Engine 控制 → LLM 产生建议 → Engine 验证 → 执行
```

**四层防护 + 质量合约**：

```
┌─────────────────────────────────────────┐
│       Guard 系统（四层防护）             │
│  • Iteration Guard (防超时)             │
│  • State Oscillation Guard (防震荡)    │
│  • Action Repetition Guard (防重复)    │
│  • Cost Guard (防超支)                  │
└──────────────┬──────────────────────────┘
               │ 包装现有
┌──────────────▼──────────────────────────┐
│       现有 Runtime (engine.py)          │
│  • LangGraph 状态图                     │
│  • LLM Client + Tool Broker             │
└──────────────┬──────────────────────────┘
               │ 新增
┌──────────────▼──────────────────────────┐
│       Contract 系统（质量验收）          │
│  • Output Contract (最终质量)          │
│  • Phase Contract (阶段质量)           │
└─────────────────────────────────────────┘
```

---

## 二、核心设计

### 2.1 核心数据结构增强

```python
from typing import TypedDict, Literal
from pydantic import BaseModel
from collections import deque

# 在现有 GraphState 基础上增加
class EnhancedAgentState(TypedDict):
    # 现有字段保持不变...
    
    # 新增：用于 Guard 检查
    state_history: deque[str]  # maxlen=20，记录状态转换历史
    action_history: deque[dict]  # maxlen=20，记录动作历史
    state_counters: dict[str, int]  # 状态计数器，避免 O(n) 遍历
    iteration: int  # 迭代次数
    token_usage: int  # Token 使用量

# Guard 检查结果
class GuardResult(BaseModel):
    blocked: bool
    reason: str = ""
    suggested_action: str = ""

# 执行结果增强
class ExecutionResult(BaseModel):
    status: Literal["SUCCESS", "TIMEOUT", "BLOCKED", "FAILED_CONTRACT", "COST_EXCEEDED", "ERROR"]
    message: str = ""
    data: dict | None = None
    partial_data: dict | None = None  # 失败时返回部分结果
    completed_phases: list[str] = []
    token_usage: int = 0
```

### 2.2 四层 Guard 系统

#### Guard 1: Iteration Guard

```python
class IterationGuard:
    """迭代次数防护"""
    def __init__(self, max_iterations: int):
        self.max_iterations = max_iterations
    
    def check(self, state: EnhancedAgentState) -> GuardResult:
        if state["iteration"] >= self.max_iterations:
            return GuardResult(
                blocked=True,
                reason=f"达到最大迭代次数 {self.max_iterations}",
                suggested_action="返回部分结果"
            )
        return GuardResult(blocked=False)
```

#### Guard 2: State Oscillation Guard（改进算法）

```python
class StateOscillationGuard:
    """状态震荡防护（检测复杂循环）"""
    def __init__(self, window_size: int = 10, min_cycle_len: int = 2):
        self.window_size = window_size
        self.min_cycle_len = min_cycle_len
    
    def check(self, state: EnhancedAgentState) -> GuardResult:
        history = list(state["state_history"])
        
        if len(history) < self.min_cycle_len * 3:
            return GuardResult(blocked=False)
        
        # 检测最近窗口中是否有循环模式
        recent = history[-self.window_size:]
        
        for cycle_len in range(self.min_cycle_len, len(recent) // 3 + 1):
            if self._has_cycle(recent, cycle_len):
                pattern = recent[-cycle_len:]
                return GuardResult(
                    blocked=True,
                    reason=f"检测到状态循环: {' → '.join(pattern)} (重复 3 次)",
                    suggested_action="强制终止"
                )
        
        return GuardResult(blocked=False)
    
    def _has_cycle(self, history: list[str], cycle_len: int) -> bool:
        """检测是否存在指定长度的循环（连续重复 3 次）"""
        if len(history) < cycle_len * 3:
            return False
        
        cycles = [
            history[i:i+cycle_len] 
            for i in range(len(history) - cycle_len * 3, len(history), cycle_len)
        ]
        
        if len(cycles) < 3:
            return False
        
        return cycles[-1] == cycles[-2] == cycles[-3]
```

#### Guard 3: Action Repetition Guard

```python
class ActionRepetitionGuard:
    """动作重复防护"""
    def __init__(self, max_repeats: int = 3):
        self.max_repeats = max_repeats
    
    def check(self, state: EnhancedAgentState) -> GuardResult:
        if len(state["action_history"]) < self.max_repeats:
            return GuardResult(blocked=False)
        
        recent_actions = list(state["action_history"])[-self.max_repeats:]
        
        if self._all_same(recent_actions):
            return GuardResult(
                blocked=True,
                reason=f"连续 {self.max_repeats} 次执行相同动作",
                suggested_action="跳过该动作"
            )
        
        return GuardResult(blocked=False)
    
    def _all_same(self, actions: list[dict]) -> bool:
        """检查动作是否完全相同"""
        if not actions:
            return False
        first = actions[0]
        return all(
            action.get("tool") == first.get("tool") and
            action.get("params") == first.get("params")
            for action in actions[1:]
        )
```

#### Guard 4: Cost Guard

```python
class CostGuard:
    """成本防护"""
    def __init__(self, total_budget: int, step_budget: int | None = None):
        self.total_budget = total_budget
        self.step_budget = step_budget or total_budget // 10
    
    def check(self, state: EnhancedAgentState) -> GuardResult:
        # 检查总预算
        if state["token_usage"] >= self.total_budget:
            return GuardResult(
                blocked=True,
                reason=f"Token 使用量 {state['token_usage']} 超出预算 {self.total_budget}",
                suggested_action="立即终止"
            )
        
        # 预估下一步成本
        if state["iteration"] > 0:
            avg_per_step = state["token_usage"] / state["iteration"]
            estimated_next = state["token_usage"] + avg_per_step
            
            if estimated_next > self.total_budget:
                return GuardResult(
                    blocked=True,
                    reason=f"预计下一步将超出预算",
                    suggested_action="完成当前状态后终止"
                )
        
        return GuardResult(blocked=False)
```

### 2.3 Contract 系统

```python
from typing import Protocol

class OutputContract(Protocol):
    """输出质量合约"""
    def validate(self, data: dict) -> GuardResult:
        """验证最终输出是否符合质量标准"""
        ...

class PhaseContract(Protocol):
    """阶段质量合约"""
    def validate(self, state: EnhancedAgentState) -> GuardResult:
        """验证当前阶段的数据质量"""
        ...


# 具体实现示例
class ClientFinderOutputContract:
    """客户发现输出合约"""
    def validate(self, data: dict) -> GuardResult:
        required_fields = ["company_name", "industry", "products", "demands"]
        missing = [f for f in required_fields if not data.get(f)]
        
        if missing:
            return GuardResult(
                blocked=True,
                reason=f"缺少必填字段: {', '.join(missing)}"
            )
        
        return GuardResult(blocked=False)
```

---

## 三、集成方案

### 3.1 包装现有 Runtime

```python
# app/runtime/controlled_engine.py

from app.runtime.engine import Runtime
from collections import deque

class ControlledRuntime:
    """包装现有 Runtime，增加 Guard 和 Contract 层"""
    
    def __init__(
        self,
        runtime: Runtime,
        max_iterations: int = 20,
        token_budget: int = 100000,
        output_contract: OutputContract | None = None,
        phase_contracts: dict[str, PhaseContract] | None = None
    ):
        self.runtime = runtime
        self.guards = self._init_guards(max_iterations, token_budget)
        self.output_contract = output_contract
        self.phase_contracts = phase_contracts or {}
    
    def _init_guards(self, max_iter: int, budget: int) -> dict[str, object]:
        return {
            "iteration": IterationGuard(max_iter),
            "oscillation": StateOscillationGuard(window_size=10),
            "repetition": ActionRepetitionGuard(max_repeats=3),
            "cost": CostGuard(budget)
        }
    
    async def run_with_guards(
        self,
        initial_state: dict,
        skill_name: str
    ) -> ExecutionResult:
        """执行 Agent，带完整防护"""
        
        # 初始化增强状态
        enhanced_state = self._enhance_state(initial_state)
        
        while True:
            # Pre-execution Guards
            guard_result = self._check_pre_guards(enhanced_state)
            if guard_result.blocked:
                return self._handle_guard_blocked(guard_result, enhanced_state)
            
            # 调用现有 Runtime 执行一步
            try:
                result = await self.runtime.execute_turn(enhanced_state)
                enhanced_state = self._update_enhanced_state(enhanced_state, result)
            except Exception as e:
                return self._handle_error(e, enhanced_state)
            
            # Post-execution Guards
            guard_result = self._check_post_guards(enhanced_state)
            if guard_result.blocked:
                return self._handle_guard_blocked(guard_result, enhanced_state)
            
            # Phase Contract 验证
            if self._should_validate_phase(enhanced_state):
                validation = self._validate_phase_contract(enhanced_state)
                if validation.blocked:
                    return self._handle_phase_failed(validation, enhanced_state)
            
            # 检查是否终止
            if enhanced_state.get("is_terminal"):
                return self._validate_and_finalize(enhanced_state)
            
            enhanced_state["iteration"] += 1
    
    def _enhance_state(self, state: dict) -> EnhancedAgentState:
        """增强现有状态"""
        return {
            **state,
            "state_history": deque(maxlen=20),
            "action_history": deque(maxlen=20),
            "state_counters": {},
            "iteration": 0,
            "token_usage": 0
        }
    
    def _check_pre_guards(self, state: EnhancedAgentState) -> GuardResult:
        """执行前检查"""
        for guard_name in ["iteration", "cost", "oscillation"]:
            result = self.guards[guard_name].check(state)
            if result.blocked:
                return result
        return GuardResult(blocked=False)
    
    def _check_post_guards(self, state: EnhancedAgentState) -> GuardResult:
        """执行后检查"""
        return self.guards["repetition"].check(state)
    
    def _validate_and_finalize(self, state: EnhancedAgentState) -> ExecutionResult:
        """验证最终输出"""
        if not self.output_contract:
            return ExecutionResult(
                status="SUCCESS",
                data=state.get("collected_data"),
                token_usage=state["token_usage"]
            )
        
        validation = self.output_contract.validate(state.get("collected_data", {}))
        
        if not validation.blocked:
            return ExecutionResult(
                status="SUCCESS",
                data=state.get("collected_data"),
                completed_phases=list(state["state_history"]),
                token_usage=state["token_usage"]
            )
        else:
            return ExecutionResult(
                status="FAILED_CONTRACT",
                message=validation.reason,
                partial_data=state.get("collected_data"),
                completed_phases=list(state["state_history"]),
                token_usage=state["token_usage"]
            )
    
    def _handle_guard_blocked(
        self, 
        guard_result: GuardResult, 
        state: EnhancedAgentState
    ) -> ExecutionResult:
        """优雅降级：返回部分结果"""
        return ExecutionResult(
            status="BLOCKED",
            message=guard_result.reason,
            partial_data=state.get("collected_data"),
            completed_phases=list(state["state_history"]),
            token_usage=state["token_usage"]
        )
```

### 3.2 在 Skill Definition 中配置

```python
# 在现有 Skill manifest.yaml 中增加配置项

metadata:
  name: "client-finder"
  version: "1.0.0"
  
execution_config:  # 新增
  max_iterations: 20
  max_same_state_count: 3
  token_budget: 50000
  enable_guards: true
  enable_phase_validation: true
  
quality_contracts:  # 新增
  output:
    type: "client_finder_output"
    required_fields:
      - company_name
      - industry
      - products
      - demands
  
  phases:
    search_company:
      type: "company_data_quality"
      min_confidence: 0.8
```

---

## 四、实施路线

### Phase 1: 核心 Guard 系统（1 周）

**目标**：实现四层 Guard，包装现有 Runtime

**交付物**：
- [ ] `IterationGuard` / `CostGuard` / `StateOscillationGuard` / `ActionRepetitionGuard`
- [ ] `ControlledRuntime` 类（包装 `Runtime`）
- [ ] 单元测试（每个 Guard 的阻止/通过条件）

**验收标准**：
```bash
pytest tests/unit/guards/ -v --cov=app.runtime.guards
# 覆盖率 >= 90%
```

---

### Phase 2: Contract 系统（3 天）

**目标**：实现 Output Contract 和 Phase Contract

**交付物**：
- [ ] `OutputContract` / `PhaseContract` Protocol
- [ ] `ClientFinderOutputContract` 示例实现
- [ ] 在 Skill manifest 中配置 contracts
- [ ] 单元测试

**验收标准**：
```bash
pytest tests/unit/contracts/ -v
```

---

### Phase 3: 集成测试（2 天）

**目标**：端到端测试，验证防护有效性

**交付物**：
- [ ] 成功场景测试
- [ ] 超时场景测试（触发 Iteration Guard）
- [ ] 循环场景测试（触发 Oscillation Guard）
- [ ] 质量不达标场景测试（触发 Contract）

**验收标准**：
```bash
pytest tests/integration/test_controlled_runtime.py -v
# 所有场景通过
```

---

## 五、关键改进点总结

| 改进维度 | 现有架构 | 优化后 |
|---------|---------|--------|
| 死循环防护 | ❌ 无 | ✅ 四层 Guard |
| 状态震荡检测 | ❌ 无 | ✅ 改进算法（检测复杂循环）|
| 质量保障 | ⚠️ 依赖 LLM 自觉 | ✅ Output + Phase Contract |
| 优雅降级 | ❌ 硬中断 | ✅ 返回部分结果 |
| 成本控制 | ⚠️ 仅统计 | ✅ 预算检查 + 预估 |
| 集成方式 | - | ✅ 包装现有 Runtime，无需大改 |

---

**实施优先级**：
1. **P0（必须）**：Iteration Guard + Oscillation Guard（解决死循环核心问题）
2. **P1（重要）**：Cost Guard + Output Contract（质量与成本控制）
3. **P2（可选）**：Phase Contract + Repetition Guard（精细化防护）

---

**文档结束**
