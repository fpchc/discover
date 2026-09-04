"""Contract 体系模型测试（W1）：三类 Contract、三态判定、序列化。"""

from __future__ import annotations

from app.runtime.contracts.models import (
    ContractDefinition,
    ContractResult,
    ContractType,
    ContractVerdict,
)


def test_contract_types_exhaustive() -> None:
    assert {t.value for t in ContractType} == {"structural", "quality", "evidence"}


def test_contract_verdicts_exhaustive() -> None:
    assert {v.value for v in ContractVerdict} == {"pass", "warn", "fail"}


def test_contract_definition_structural() -> None:
    definition = ContractDefinition(
        contract_id="schema.check",
        contract_type=ContractType.STRUCTURAL,
        required_fields=["name", "score"],
        retryable=False,
    )
    restored = ContractDefinition.model_validate_json(definition.model_dump_json())
    assert restored.required_fields == ["name", "score"]
    assert restored.max_repair_attempts == 0


def test_contract_result_pass() -> None:
    result = ContractResult(
        contract_id="schema.check",
        contract_type=ContractType.STRUCTURAL,
        verdict=ContractVerdict.PASS,
        score=1.0,
    )
    assert result.verdict == ContractVerdict.PASS
    restored = ContractResult.model_validate_json(result.model_dump_json())
    assert restored.score == 1.0


def test_contract_result_fail_with_remediation() -> None:
    result = ContractResult(
        contract_id="evidence.check",
        contract_type=ContractType.EVIDENCE,
        verdict=ContractVerdict.FAIL,
        failures=["结论缺证据关联"],
        remediation="补充来源记录",
        retryable=True,
        fallback="degrade_to_warning",
    )
    assert result.failures == ["结论缺证据关联"]
    assert result.retryable is True
    assert result.fallback == "degrade_to_warning"


def test_contract_result_defaults() -> None:
    result = ContractResult(
        contract_id="q",
        contract_type=ContractType.QUALITY,
        verdict=ContractVerdict.WARN,
    )
    assert result.failures == []
    assert result.score is None
