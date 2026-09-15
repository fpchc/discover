"""Contract 体系：定义 / 执行器注册表 / 结果统一 / 有界修复。"""

from app.harness.contracts.executor import (
    ContractContext,
    ContractExecutor,
    EvidenceContractExecutor,
    GateRunnerPort,
    QualityContractExecutor,
    ScriptGateExecutor,
    StructuralContractExecutor,
)
from app.harness.contracts.models import (
    ContractDefinition,
    ContractResult,
    ContractType,
    ContractVerdict,
)
from app.harness.contracts.registry import ContractRegistry, decide_repair
from app.harness.contracts.structural import has_structural_contract, structural_failures

__all__ = [
    "ContractContext",
    "ContractDefinition",
    "ContractExecutor",
    "ContractRegistry",
    "ContractResult",
    "ContractType",
    "ContractVerdict",
    "EvidenceContractExecutor",
    "GateRunnerPort",
    "QualityContractExecutor",
    "ScriptGateExecutor",
    "StructuralContractExecutor",
    "decide_repair",
    "has_structural_contract",
    "structural_failures",
]
