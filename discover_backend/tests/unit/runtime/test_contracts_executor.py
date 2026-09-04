"""Contract 体系测试（W5，§14）：三类执行器、门禁统一、注册表、有界修复。"""

from __future__ import annotations

from app.capabilities.tools.broker import ToolResult
from app.runtime.contracts.executor import (
    ContractContext,
    EvidenceContractExecutor,
    GateRunnerPort,
    QualityContractExecutor,
    ScriptGateExecutor,
    StructuralContractExecutor,
)
from app.runtime.contracts.models import (
    ContractDefinition,
    ContractResult,
    ContractType,
    ContractVerdict,
)
from app.runtime.contracts.registry import ContractRegistry, decide_repair
from app.runtime.policy.models import PolicyDecisionType


# ---- Structural：必填字段 + 产物存在性 ----
async def test_structural_pass() -> None:
    executor = StructuralContractExecutor()
    definition = ContractDefinition(
        contract_id="schema",
        contract_type=ContractType.STRUCTURAL,
        required_fields=["name", "score"],
    )
    result = await executor.execute(definition, ContractContext(data={"name": "x", "score": 1}))
    assert result.verdict == ContractVerdict.PASS


async def test_structural_missing_field_fails() -> None:
    executor = StructuralContractExecutor()
    definition = ContractDefinition(
        contract_id="schema",
        contract_type=ContractType.STRUCTURAL,
        required_fields=["name"],
    )
    result = await executor.execute(definition, ContractContext(data={"other": 1}))
    assert result.verdict == ContractVerdict.FAIL
    assert any("name" in failure for failure in result.failures)


async def test_structural_required_artifact() -> None:
    executor = StructuralContractExecutor()
    definition = ContractDefinition(
        contract_id="artifact",
        contract_type=ContractType.STRUCTURAL,
        require_artifacts=["report.txt"],
    )
    result = await executor.execute(definition, ContractContext(artifact_ids=[]))
    assert result.verdict == ContractVerdict.FAIL


# ---- Quality：数量 / 数据源 ----
async def test_quality_min_count() -> None:
    executor = QualityContractExecutor()
    definition = ContractDefinition(
        contract_id="quality",
        contract_type=ContractType.QUALITY,
        min_count=3,
    )
    result = await executor.execute(definition, ContractContext(data={"a": 1, "b": 2}))
    assert result.verdict == ContractVerdict.FAIL


async def test_quality_data_sources() -> None:
    executor = QualityContractExecutor()
    definition = ContractDefinition(
        contract_id="sources",
        contract_type=ContractType.QUALITY,
        min_data_sources=2,
    )
    result = await executor.execute(definition, ContractContext(sources=["a"]))
    assert result.verdict == ContractVerdict.FAIL


# ---- Evidence：证据关联 ----
async def test_evidence_requires_refs() -> None:
    executor = EvidenceContractExecutor()
    definition = ContractDefinition(
        contract_id="evidence",
        contract_type=ContractType.EVIDENCE,
        require_evidence=True,
    )
    result = await executor.execute(definition, ContractContext(evidence_refs=[]))
    assert result.verdict == ContractVerdict.FAIL


async def test_evidence_pass_with_refs_and_sources() -> None:
    executor = EvidenceContractExecutor()
    definition = ContractDefinition(
        contract_id="evidence",
        contract_type=ContractType.EVIDENCE,
        require_evidence=True,
        require_source_trace=True,
    )
    result = await executor.execute(
        definition, ContractContext(evidence_refs=["e1"], sources=["tencent_mcp"])
    )
    assert result.verdict == ContractVerdict.PASS


# ---- 门禁统一：既有 Gate 脚本归一为 ContractExecutor（§14.1）----
class _FakeGateRunner(GateRunnerPort):
    def __init__(self, ok: bool = True) -> None:
        self._ok = ok

    async def run_gate(self, *, gate_id: str, data: dict[str, object]) -> ToolResult:
        if self._ok:
            return ToolResult(call_id="g", tool_name=f"gate_{gate_id}", ok=True, content="校验通过")
        return ToolResult(
            call_id="g",
            tool_name=f"gate_{gate_id}",
            ok=False,
            message="数据不完整",
            suggestion="补充企业名称后重试",
        )


async def test_gate_unified_as_contract_executor() -> None:
    definition = ContractDefinition(
        contract_id="enterprise_completeness",
        contract_type=ContractType.QUALITY,
        retryable=True,
    )
    executor = ScriptGateExecutor(_FakeGateRunner(ok=True))
    result = await executor.execute(definition, ContractContext(data={"name": "企业A"}))
    assert result.verdict == ContractVerdict.PASS


async def test_gate_fail_carries_remediation() -> None:
    definition = ContractDefinition(
        contract_id="enterprise_completeness",
        contract_type=ContractType.QUALITY,
        retryable=True,
    )
    executor = ScriptGateExecutor(_FakeGateRunner(ok=False))
    result = await executor.execute(definition, ContractContext(data={}))
    assert result.verdict == ContractVerdict.FAIL
    assert result.remediation == "补充企业名称后重试"


# ---- 注册表 ----
def test_registry_resolves_by_type() -> None:
    registry = ContractRegistry(
        [
            StructuralContractExecutor(),
            QualityContractExecutor(),
            EvidenceContractExecutor(),
        ]
    )
    definition = ContractDefinition(contract_id="s", contract_type=ContractType.STRUCTURAL)
    assert isinstance(registry.resolve(definition), StructuralContractExecutor)


def test_registry_unknown_type_raises() -> None:
    registry = ContractRegistry([])
    definition = ContractDefinition(contract_id="x", contract_type=ContractType.QUALITY)
    try:
        registry.resolve(definition)
    except KeyError:
        return
    raise AssertionError("应抛 KeyError")


# ---- 有界修复（§14.4）：FAIL 不无限修复 ----
def test_repair_pass_allows() -> None:
    result = ContractResult(
        contract_id="c", contract_type=ContractType.STRUCTURAL, verdict=ContractVerdict.PASS
    )
    decision = decide_repair(result, repair_attempts=0, max_repair_attempts=2)
    assert decision.decision == PolicyDecisionType.ALLOW


def test_repair_retry_within_budget() -> None:
    result = ContractResult(
        contract_id="c",
        contract_type=ContractType.STRUCTURAL,
        verdict=ContractVerdict.FAIL,
        retryable=True,
        remediation="补数据",
    )
    decision = decide_repair(result, repair_attempts=0, max_repair_attempts=2)
    assert decision.decision == PolicyDecisionType.RETRY
    assert decision.attempt == 1


def test_repair_exhausted_terminates() -> None:
    result = ContractResult(
        contract_id="c",
        contract_type=ContractType.STRUCTURAL,
        verdict=ContractVerdict.FAIL,
        retryable=True,
    )
    decision = decide_repair(result, repair_attempts=2, max_repair_attempts=2)
    assert decision.decision == PolicyDecisionType.TERMINATE
    assert decision.recoverable is False


def test_repair_degrade_with_fallback() -> None:
    result = ContractResult(
        contract_id="c",
        contract_type=ContractType.STRUCTURAL,
        verdict=ContractVerdict.FAIL,
        fallback="degrade_to_warning",
    )
    decision = decide_repair(result, repair_attempts=2, max_repair_attempts=2)
    assert decision.decision == PolicyDecisionType.DEGRADE
    assert decision.fallback_phase == "degrade_to_warning"
