"""Contract 体系：定义 / 执行器注册表 / 结果统一 / 有界修复。"""

from app.runtime.contracts.executor import (
    ContractContext,
    ContractExecutor,
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
