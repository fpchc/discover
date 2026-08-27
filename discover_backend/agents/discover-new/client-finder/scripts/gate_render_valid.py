#!/usr/bin/env python3
"""门禁校验器：render_pass — 报告结构完整性校验。

契约（agent-package-spec §7）：stdin 一次写入 UTF-8 JSON，stdout 输出 UTF-8 JSON；
退出码 0 = 通过，非 0 = 未通过（stdout 给出失败项清单）。

入参：{"report_json": "<工作区相对路径或容器内绝对路径>"} 或平台默认 {"input": "<路径>"}
出参：{"passed": bool, "errors": [...], "warnings": [...]}

仅做结构校验（阻断级，收窄为 clients 非空数组），字段齐全/数据完整性项降级为 warnings，不阻断。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import render_report

WORKSPACE_DIR = Path(os.environ.get("WORKSPACE_DIR", str(Path.cwd())))


def resolve_report_path(raw: str) -> Path:
    p = Path(raw)
    if p.is_absolute():
        return p
    return WORKSPACE_DIR / p


def main() -> None:
    raw = sys.stdin.read()
    try:
        data: dict[str, Any] = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(
            json.dumps(
                {"passed": False, "errors": [f"JSON 解析失败: {exc}"], "warnings": []},
                ensure_ascii=False,
            )
        )
        sys.exit(1)
    report_arg = str(data.get("report_json") or data.get("input") or "").strip()
    if not report_arg:
        print(
            json.dumps(
                {"passed": False, "errors": ["缺少 report_json / input 参数"], "warnings": []},
                ensure_ascii=False,
            )
        )
        sys.exit(1)
    report_path = resolve_report_path(str(report_arg))
    if not report_path.is_file():
        print(
            json.dumps(
                {"passed": False, "errors": [f"报告 JSON 不存在: {report_path}"], "warnings": []},
                ensure_ascii=False,
            )
        )
        sys.exit(1)
    with open(report_path, encoding="utf-8") as f:
        report: dict[str, Any] = json.load(f)
    errors = render_report.validate_structure(report)
    warnings = render_report.check_completeness(report) + render_report.check_density(report)
    passed = len(errors) == 0
    print(
        json.dumps(
            {"passed": passed, "errors": errors, "warnings": warnings}, ensure_ascii=False, indent=2
        )
    )
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
