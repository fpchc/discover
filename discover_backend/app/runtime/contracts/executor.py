"""ContractExecutor（react-runtime-v2-architecture §14）。

单一动机：把 ContractDefinition 执行为 ContractResult，供 Workflow Transition 使用。
三类实现（structural / quality / evidence）+ ScriptGateExecutor（现有 Gate 脚本统一
为 ContractExecutor 实现，§14.1，不建平行体系）。

依赖抽象：GateRunnerPort 供 ScriptGateExecutor 调用既有门禁脚本工具；真实执行经
ToolRuntime 组装层适配，测试注入桩（DIP，CLAUDE.md §6）。
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field

from app.capabilities.tools.broker import ToolResult
from app.runtime.contracts.models import (
    ContractDefinition,
    ContractResult,
    ContractType,
    ContractVerdict,
)


class ContractContext(BaseModel):
    """Contract 执行上下文：候选输出 + 证据/产物引用 + 数据源（§14.2）。"""

    data: dict[str, object] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)
    artifact_ids: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


class ContractExecutor(Protocol):
    """Contract 执行抽象：定义 + 上下文 → 结果。"""

    contract_type: ContractType

    async def execute(
        self, definition: ContractDefinition, context: ContractContext
    ) -> ContractResult: ...


class GateRunnerPort(Protocol):
    """门禁脚本执行抽象：既有 gate_<id> 脚本工具经此执行（组装层适配）。"""

    async def run_gate(self, *, gate_id: str, data: dict[str, object]) -> ToolResult: ...


class StructuralContractExecutor:
    """Structural Contract（§14.2）：必填字段 + JSON Schema 子集 + 产物存在性。"""

    contract_type: ContractType = ContractType.STRUCTURAL

    async def execute(
        self, definition: ContractDefinition, context: ContractContext
    ) -> ContractResult:
        failures: list[str] = []
        warnings: list[str] = []
        missing = [field for field in definition.required_fields if field not in context.data]
        if missing:
            failures.append(f"缺少必填字段：{', '.join(missing)}")
        for artifact in definition.require_artifacts:
            if artifact not in context.artifact_ids:
                failures.append(f"缺少必需产物：{artifact}")
        verdict = _verdict(failures, warnings)
        return ContractResult(
            contract_id=definition.contract_id,
            contract_type=definition.contract_type,
            verdict=verdict,
            failures=failures,
            warnings=warnings,
            retryable=definition.retryable,
            fallback=definition.fallback,
        )


class QualityContractExecutor:
    """Quality Contract（§14.2）：数量 / 覆盖率 / 置信度 / 数据源数量。"""

    contract_type: ContractType = ContractType.QUALITY

    async def execute(
        self, definition: ContractDefinition, context: ContractContext
    ) -> ContractResult:
        failures: list[str] = []
        score = 1.0
        if definition.min_count is not None:
            count = len(context.data)
            if count < definition.min_count:
                failures.append(f"数据量不足（{count}/{definition.min_count}）")
                score = min(score, count / definition.min_count if definition.min_count else 0.0)
        if (
            definition.min_data_sources is not None
            and len(context.sources) < definition.min_data_sources
        ):
            failures.append(f"数据源不足（{len(context.sources)}/{definition.min_data_sources}）")
        verdict = ContractVerdict.PASS if not failures else ContractVerdict.FAIL
        return ContractResult(
            contract_id=definition.contract_id,
            contract_type=definition.contract_type,
            verdict=verdict,
            failures=failures,
            score=score,
            retryable=definition.retryable,
            fallback=definition.fallback,
        )


class EvidenceContractExecutor:
    """Evidence Contract（§14.2）：关键结论关联证据 / 来源记录 / 推断标记。"""

    contract_type: ContractType = ContractType.EVIDENCE

    async def execute(
        self, definition: ContractDefinition, context: ContractContext
    ) -> ContractResult:
        failures: list[str] = []
        warnings: list[str] = []
        if definition.require_evidence and not context.evidence_refs:
            failures.append("关键结论缺少证据关联")
        if definition.require_source_trace and not context.sources:
            failures.append("数据源未记录")
        if context.evidence_refs and not context.sources:
            warnings.append("存在证据但未记录来源")
        verdict = _verdict(failures, warnings)
        return ContractResult(
            contract_id=definition.contract_id,
            contract_type=definition.contract_type,
            verdict=verdict,
            failures=failures,
            warnings=warnings,
            evidence_summary=", ".join(context.evidence_refs),
            retryable=definition.retryable,
            fallback=definition.fallback,
        )


class ScriptGateExecutor:
    """现有 Gate 脚本统一为 ContractExecutor（§14.1）。

    把既有 ``gate_<id>`` 脚本工具的 ToolResult 归一为 ContractResult：
    脚本成功（ok=True）→ PASS；失败 → FAIL 并携带脚本信息作为 remediation。
    """

    contract_type: ContractType = ContractType.QUALITY

    def __init__(self, runner: GateRunnerPort) -> None:
        self._runner = runner

    async def execute(
        self, definition: ContractDefinition, context: ContractContext
    ) -> ContractResult:
        result = await self._runner.run_gate(gate_id=definition.contract_id, data=context.data)
        if result.ok:
            return ContractResult(
                contract_id=definition.contract_id,
                contract_type=definition.contract_type,
                verdict=ContractVerdict.PASS,
                score=1.0,
                evidence_summary=result.content[:500],
                retryable=definition.retryable,
                fallback=definition.fallback,
            )
        return ContractResult(
            contract_id=definition.contract_id,
            contract_type=definition.contract_type,
            verdict=ContractVerdict.FAIL,
            failures=[result.message],
            remediation=result.suggestion or result.message,
            retryable=definition.retryable,
            fallback=definition.fallback,
        )


def _verdict(failures: list[str], warnings: list[str]) -> ContractVerdict:
    if failures:
        return ContractVerdict.FAIL
    if warnings:
        return ContractVerdict.WARN
    return ContractVerdict.PASS
