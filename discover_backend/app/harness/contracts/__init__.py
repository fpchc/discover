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
]
