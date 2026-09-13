#!/usr/bin/env python3
"""门禁校验器：render_pass — 报告交付结构校验。

契约（agent-package-spec §7）：stdin 一次写入 UTF-8 JSON，stdout 输出 UTF-8 JSON；
退出码 0 = 通过，非 0 = 未通过。

两种入参：
- 新契约（Markdown 交付，输出契约默认）：{"answer": "<完整 Markdown 报告正文>"}
- 旧契约（JSON 渲染产物，兼容集成测试/历史调用）：{"report_json": "<相对或绝对路径>"}

Markdown 阻断级：
- 必备章节缺失（评分 / 决策人 / 切入策略 / 风险）
- 占位符残留
- 工具名 / 脚本名 / 模板名泄露
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import render_report

WORKSPACE_DIR = Path(os.environ.get("WORKSPACE_DIR", str(Path.cwd())))

REQUIRED_MARKERS: tuple[str, ...] = ("评分", "决策人", "切入", "风险")
PLACEHOLDER_MARKERS: tuple[str, ...] = (
    "XXX",
    "TODO",
    "TBD",
    "占位",
    "待补充",
    "待填",
    "placeholder",
)
LEAK_PATTERNS: tuple[str, ...] = (
    "score_calculator",
    "render_report",
    "gate_render_valid",
    "cfr.html",
    "report_schema",
    ".py",
    ".json",
    ".html",
)


def check_markdown(answer: str) -> tuple[list[str], list[str]]:
    """校验 Markdown 报告正文，返回 (errors, warnings)。"""
    errors: list[str] = []
    warnings: list[str] = []
    for marker in REQUIRED_MARKERS:
        if marker not in answer:
            errors.append(f"缺少必备章节/要素：{marker}")
    lowered = answer.lower()
    for marker in PLACEHOLDER_MARKERS:
        if marker.lower() in lowered:
            errors.append(f"含占位符：{marker}")
    for pattern in LEAK_PATTERNS:
        if pattern.lower() in lowered:
            errors.append(f"泄露内部机制名：{pattern}")
    return errors, warnings


def resolve_report_path(raw: str) -> Path:
    p = Path(raw)
    if p.is_absolute():
        return p
    return WORKSPACE_DIR / p


def _emit(passed: bool, errors: list[str], warnings: list[str]) -> None:
    print(
        json.dumps(
            {"passed": passed, "errors": errors, "warnings": warnings},
            ensure_ascii=False,
            indent=2,
        )
    )
    sys.exit(0 if passed else 1)


def main() -> None:
    raw = sys.stdin.read()
    try:
        data: dict[str, Any] = json.loads(raw)
    except json.JSONDecodeError as exc:
        _emit(False, [f"JSON 解析失败: {exc}"], [])
        return
    answer = data.get("answer")
    if isinstance(answer, str) and answer.strip():
        errors, warnings = check_markdown(answer)
        _emit(len(errors) == 0, errors, warnings)
        return
    report_arg = str(data.get("report_json") or data.get("input") or "").strip()
    if not report_arg:
        _emit(False, ["缺少 answer 或 report_json / input 参数"], [])
        return
    report_path = resolve_report_path(report_arg)
    if not report_path.is_file():
        _emit(False, [f"报告 JSON 不存在: {report_path}"], [])
        return
    with open(report_path, encoding="utf-8") as f:
        report: dict[str, Any] = json.load(f)
    errors = render_report.validate_structure(report)
    warnings = render_report.check_completeness(report) + render_report.check_density(report)
    _emit(len(errors) == 0, errors, warnings)


if __name__ == "__main__":
    main()
