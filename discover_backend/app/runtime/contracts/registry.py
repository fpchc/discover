"""ContractExecutor 注册表与有界修复（react-runtime-v2-architecture §14）。

单一动机：
- 注册表：ContractDefinition 按类型解析到 ContractExecutor 实现（§14.1 统一入口）。
- 有界修复：ContractResult → Workflow Transition（§9.3 / §14.4），受 max_repair_attempts
  与独立 repair budget 约束，Contract 不得制造无限返工循环。
"""

from __future__ import annotations

from app.runtime.contracts.executor import ContractExecutor
from app.runtime.contracts.models import (
    ContractDefinition,
    ContractResult,
    ContractType,
    ContractVerdict,
)
from app.runtime.policy.models import PolicyDecision, PolicyDecisionType


class ContractRegistry:
    """按 ContractType 注册并解析执行器（策略注册表，OCP）。"""

    def __init__(self, executors: list[ContractExecutor]) -> None:
        self._executors: dict[ContractType, ContractExecutor] = {
            executor.contract_type: executor for executor in executors
        }

    def resolve(self, definition: ContractDefinition) -> ContractExecutor:
        executor = self._executors.get(definition.contract_type)
        if executor is None:
            raise KeyError(f"未注册的 Contract 类型：{definition.contract_type}")
        return executor


def decide_repair(
    result: ContractResult,
    *,
    repair_attempts: int,
    max_repair_attempts: int,
) -> PolicyDecision:
    """Contract 失败后的路径决策（§14.4 / §9.3）。

    规则：
    - PASS/WARN → ALLOW（可继续推进）；
    - FAIL + retryable + 未超上限 → RETRY（回到当前 Phase）；
    - FAIL + 有 fallback → DEGRADE（固化带限制输出）；
    - FAIL + 无 fallback + 已达修复上限 → TERMINATE（FAIL run 或 partial）。
    """
    if result.verdict in {ContractVerdict.PASS, ContractVerdict.WARN}:
        return PolicyDecision(decision=PolicyDecisionType.ALLOW, reason_code="contract_ok")
    if result.retryable and repair_attempts < max_repair_attempts:
        return PolicyDecision(
            decision=PolicyDecisionType.RETRY,
            reason_code=f"contract_repair:{result.contract_id}",
            display_message=result.remediation or "Contract 校验失败，回到当前阶段修复",
            attempt=repair_attempts + 1,
            recoverable=True,
        )
    if result.fallback:
        return PolicyDecision(
            decision=PolicyDecisionType.DEGRADE,
            reason_code=f"contract_degrade:{result.fallback}",
            display_message="Contract 未通过，降级后继续",
            fallback_phase=result.fallback,
            recoverable=True,
        )
    return PolicyDecision(
        decision=PolicyDecisionType.TERMINATE,
        reason_code=f"contract_failed:{result.contract_id}",
        display_message=result.remediation or "Contract 校验失败且不可修复",
        recoverable=False,
    )
