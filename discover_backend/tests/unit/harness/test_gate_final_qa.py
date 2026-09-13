"""gate_final_qa 校验器单测：逐卡字数 / 排版 / 行内 --- / 泄露。

通过 importlib 直接加载技能脚本，只测纯函数 check / _split_cards，不发起真实
网络 / DB / LLM。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent.parent
GATE_PATH = ROOT / "agents" / "discover-new" / "client-finder" / "scripts" / "gate_final_qa.py"


def _load_gate() -> Any:  # noqa: ANN401  # 动态加载技能脚本模块
    spec = importlib.util.spec_from_file_location("gate_final_qa_under_test", GATE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_card(repeat: int = 220) -> str:
    """构造一张满足三段式与加粗标签行的信息卡。"""
    return (
        "**电子元器件分销商，深圳宝安，未上市**，成立于2021年，注册资本1000万元。\n\n"
        f"**主营**：{'信息' * repeat}\n\n"
        "**切入**：适合以标准品批量供应切入。"
    )


def test_valid_single_card_passes() -> None:
    gate = _load_gate()
    card = _make_card()
    assert 450 <= len(gate._strip_markup(card)) <= 550
    errors, _ = gate.check(card)
    assert errors == []


def test_too_short_card_fails() -> None:
    gate = _load_gate()
    errors, _ = gate.check("**定位**：很短")
    assert any("低于 450" in error for error in errors)


def test_inline_dash_separator_fails() -> None:
    gate = _load_gate()
    card = _make_card() + " 行内---尾巴"
    errors, _ = gate.check(card)
    assert any("行内 ---" in error for error in errors)


def test_leak_fails() -> None:
    gate = _load_gate()
    card = _make_card() + " score_calculator"
    errors, _ = gate.check(card)
    assert any("泄露" in error for error in errors)


def test_multi_card_validates_each_card() -> None:
    gate = _load_gate()
    answer = f"{_make_card()}\n\n---\n\n{_make_card()}"
    errors, _ = gate.check(answer)
    assert errors == []
    cards = gate._split_cards(answer)
    assert len(cards) == 2
