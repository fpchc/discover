"""Contract 体系模型（react-runtime-v2-architecture §14，P0-2 接缝）。

单一动机：定义「阶段是否真正完成」的确定性判定契约。三类 Contract
（structural / quality / evidence）+ PASS / WARN / FAIL 三态结果；
有界修复受 max_repair_attempts 与 repair budget 约束，不制造无限返工循环。
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class ContractType(StrEnum):
    """Contract 类型（§14.2）。"""

    STRUCTURAL = "structural"
    QUALITY = "quality"
    EVIDENCE = "evidence"


class ContractVerdict(StrEnum):
    """Contract 判定（§14.3）。"""

    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


class ContractDefinition(BaseModel):
    """Contract 定义（§14.2）：由 Skill Pack 声明，平台只解释通用结构。

    平台不包含具体业务 Contract 类；现有 Gate 脚本统一为 ContractExecutor 实现
    （§14.1），不建平行体系。
    """

    contract_id: str
    contract_type: ContractType
    description: str = ""
    # structural：JSON Schema / 必填字段 / 产物存在性
    json_schema: dict[str, object] | None = None
    required_fields: list[str] = Field(default_factory=list)
    require_artifacts: list[str] = Field(default_factory=list)
    # quality：数量 / 覆盖率 / 置信度 / 数据源数量
    min_count: int | None = None
    min_coverage: float | None = None
    min_confidence: float | None = None
    min_data_sources: int | None = None
    custom_metrics: dict[str, float] = Field(default_factory=dict)
    # evidence：结论 → 证据关联
    require_evidence: bool = False
    require_source_trace: bool = False
    require_inference_marked: bool = False
    # 有界修复（§14.4）
    retryable: bool = False
    max_repair_attempts: int = 0
    fallback: str = ""


class ContractResult(BaseModel):
    """Contract 执行结果（§14.3）：三态 + 失败/警告 + 修复指引。"""

    contract_id: str
    contract_type: ContractType
    verdict: ContractVerdict
    failures: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    score: float | None = None
    evidence_summary: str = ""
    remediation: str = ""
    retryable: bool = False
    fallback: str = ""
