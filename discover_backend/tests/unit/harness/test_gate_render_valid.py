"""discover render_pass 门禁单测：Markdown 模式结构校验。

通过 importlib 加载技能脚本，只测纯函数 check_markdown，不发起真实网络 / DB / LLM。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SCRIPTS_DIR = ROOT / "agents" / "discover" / "client-finder" / "scripts"
GATE_PATH = SCRIPTS_DIR / "gate_render_valid.py"


def _load_gate() -> Any:  # noqa: ANN401  # 动态加载技能脚本模块
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    spec = importlib.util.spec_from_file_location("gate_render_valid_under_test", GATE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _valid_report() -> str:
    return (
        "# 客户发现报告\n\n"
        "评分：八维量化综合分 7.63。\n\n"
        "决策人：张三（总经理）。\n\n"
        "切入策略：以标准品批量供应切入。\n\n"
        "风险：无失信、无被执行记录。"
    )


def test_markdown_valid_passes() -> None:
    gate = _load_gate()
    errors, _ = gate.check_markdown(_valid_report())
    assert errors == []


def test_markdown_missing_section_fails() -> None:
    gate = _load_gate()
    errors, _ = gate.check_markdown("评分：八维。决策人：张三。")
    assert any("切入" in error for error in errors)
    assert any("风险" in error for error in errors)


def test_markdown_leak_fails() -> None:
    gate = _load_gate()
    errors, _ = gate.check_markdown(_valid_report() + " score_calculator")
    assert any("泄露" in error for error in errors)


def test_markdown_placeholder_fails() -> None:
    gate = _load_gate()
    errors, _ = gate.check_markdown(_valid_report() + " TODO 待补充")
    assert any("占位" in error for error in errors)
