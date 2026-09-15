"""结构契约校验（JSON Schema 子集）：必填字段存在性 + 基础类型。

单一动机：把「阶段候选输出是否满足结构契约」抽成一处确定性判定，供
阶段转换点（WorkflowRunner 过程闸门）与 Verifier（终点兜底）共用同一实现，
避免两处实现漂移。

职责边界（与 StructuralContractExecutor 正交，两者不合并）：
- 本模块只解释 ``PhaseDefinition.output_schema``（经 outcome.output_schema 透传）
  的 JSON Schema 子集（``required`` + ``properties.type``），不感知 ContractDefinition；
- ``StructuralContractExecutor``（contracts/executor.py）解释 ``ContractDefinition``
  的 ``required_fields`` / ``require_artifacts``，由 ``contract_refs`` 驱动。
二者是两条不同的契约输入：阶段转换点校验 output_schema，contract_refs 执行时走
ContractExecutor。
"""

from __future__ import annotations


def structural_failures(
    output_schema: dict[str, object], candidate_output: dict[str, object] | None
) -> list[str]:
    """结构契约校验（JSON Schema 子集）：必填字段存在性 + 基础类型。"""
    required = _required_fields(output_schema)
    if candidate_output is None:
        if required:
            return [f"缺少必填字段：{', '.join(required)}"]
        return ["候选输出为空"]
    failures = [f"缺少必填字段：{field}" for field in required if field not in candidate_output]
    failures.extend(
        f"字段 {field} 类型不符"
        for field, value in candidate_output.items()
        if not _type_matches(output_schema, field, value)
    )
    return failures


def has_structural_contract(output_schema: dict[str, object]) -> bool:
    """schema 是否声明了可校验的结构契约（有 required 或 properties）。"""
    return bool(_required_fields(output_schema)) or isinstance(
        output_schema.get("properties"), dict
    )


def _required_fields(output_schema: dict[str, object]) -> list[str]:
    raw = output_schema.get("required")
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, str)]
    return []


def _type_matches(output_schema: dict[str, object], field: str, value: object) -> bool:
    props = output_schema.get("properties")
    if not isinstance(props, dict):
        return True
    field_schema = props.get(field)
    if not isinstance(field_schema, dict):
        return True
    declared = field_schema.get("type")
    if not isinstance(declared, str):
        return True
    if value is None:
        return True
    if declared == "string":
        return isinstance(value, str)
    if declared == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if declared == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if declared == "boolean":
        return isinstance(value, bool)
    return True


__all__ = ["has_structural_contract", "structural_failures"]
