#!/usr/bin/env python3
"""账期评估 — 报告结构校验器（门禁 gate_report_valid，P1）。

契约：stdin 一次写入 UTF-8 JSON，stdout 输出 UTF-8 JSON。
退出码 0 = 通过；非 0 = 未通过，stdout 给结构化失败项清单（供模型逐项修复后重跑）。

校验项：
  1. 章节完整性：10 个必备章节均存在且非空
  2. 占位符残留：任一章节含占位标记即失败
  3. 评分一致性：红线阻断（composite_score=null）→ 账期 0 且等级 D；非阻断 → 账期 > 0；
     账期不超过客户应收周转天数（AR 硬约束）

用法：
  python gate_report_valid.py < input.json
  python gate_report_valid.py '{"report": {...}}'
  python gate_report_valid.py --test
"""

from __future__ import annotations

import io
import json
import sys
from typing import Any

REQUIRED_SECTIONS: list[str] = [
    "cover",
    "conclusion",
    "basic_info",
    "financial",
    "credit_risk",
    "stability",
    "demand",
    "risk_signals",
    "monitoring",
    "appendix",
]

# 占位符标记（大小写不敏感匹配）
PLACEHOLDER_MARKERS: tuple[str, ...] = (
    "XXX",
    "待补充",
    "TODO",
    "TBD",
    "占位",
    "推测#",
    "？？",
    "待确认",
    "PLACEHOLDER",
)

# 有效授信等级
VALID_GRADES: tuple[str, ...] = ("S", "A", "B", "C", "D")


def _contains_placeholder(text: str) -> bool:
    """检测文本是否含占位符标记。"""
    upper = text.upper()
    return any(marker.upper() in upper for marker in PLACEHOLDER_MARKERS)


def validate_report(report: dict[str, Any]) -> list[str]:
    """校验报告结构与评分一致性，返回失败项列表（空列表 = 通过）。"""
    failures: list[str] = []

    sections = report.get("sections")
    if not isinstance(sections, dict):
        failures.append("缺少 sections 对象")
        sections = {}

    for section in REQUIRED_SECTIONS:
        text = sections.get(section)
        if not isinstance(text, str) or not text.strip():
            failures.append(f"缺少章节 {section} 或内容为空")
        elif _contains_placeholder(text):
            failures.append(f"章节 {section} 含占位符")

    # 评分一致性
    cs = report.get("composite_score")
    grade = report.get("credit_grade")
    days = report.get("recommended_credit_days")
    ar_days = report.get("ar_days")
    limit = report.get("credit_limit")

    if cs is not None and (not isinstance(cs, (int, float)) or not (0 <= float(cs) <= 10)):
        failures.append(f"composite_score 须在 0-10 或为 null，当前 {cs!r}")
    if grade not in VALID_GRADES:
        failures.append(f"credit_grade 非法 {grade!r}，须为 S/A/B/C/D")
    if isinstance(days, (int, float)) and days < 0:
        failures.append(f"recommended_credit_days 不能为负：{days}")
    if isinstance(limit, (int, float)) and limit < 0:
        failures.append(f"credit_limit 不能为负：{limit}")

    if cs is None:
        # 红线阻断场景
        if isinstance(days, (int, float)) and days != 0:
            failures.append("红线阻断（composite_score=null）时建议账期应为 0")
        if grade != "D":
            failures.append("红线阻断（composite_score=null）时授信等级应为 D")
    else:
        # 正常授信场景
        if isinstance(days, (int, float)) and days == 0 and grade != "D":
            failures.append("非阻断客户建议账期不能为 0")
        if (
            isinstance(ar_days, (int, float))
            and ar_days > 0
            and isinstance(days, (int, float))
            and days > ar_days
        ):
            failures.append(f"建议账期 {days} 天超客户应收周转 {ar_days} 天（AR 硬约束）")

    return failures


def _emit_error(message: str) -> None:
    print(json.dumps({"error": message}, ensure_ascii=False))
    sys.exit(1)


def main() -> None:
    # Windows 控制台默认 GBK，统一重定向 stdout 为 UTF-8 避免中文打印报错
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    if "--test" in sys.argv:
        _run_tests()
        return

    raw = sys.argv[1] if len(sys.argv) > 1 else sys.stdin.buffer.read().decode("utf-8")
    try:
        data: Any = json.loads(raw)
    except json.JSONDecodeError as exc:
        _emit_error(f"JSON 解析失败: {exc}")
    if not isinstance(data, dict) or "report" not in data:
        _emit_error("缺少 report 对象")
    report = data["report"]
    if not isinstance(report, dict):
        _emit_error("report 必须是对象")

    failures = validate_report(report)
    if failures:
        print(json.dumps({"ok": False, "failures": failures}, ensure_ascii=False, indent=2))
        sys.exit(1)
    print(json.dumps({"ok": True, "failures": []}, ensure_ascii=False, indent=2))


# ═══════════════════════════════════════════════════════════
# 冒烟测试
# ═══════════════════════════════════════════════════════════


def _build_good_report() -> dict[str, Any]:
    """构造一份合法报告（章节非空且无占位符）。"""
    return {
        "company_name": "凯格精机",
        "sections": {
            "cover": "委托方：销售部；客户：凯格精机；日期：2026-08-29；数据来源：P1 公开搜索。",
            "conclusion": "S级 · 建议账期 44 天 · 建议额度约 59 万元。",
            "basic_info": "注册资本、成立日期、地址、经营状态：在营。",
            "financial": "上市财报：负债率39.68%、毛利率41.26%、应收周转44天。",
            "credit_risk": "被执行0条、欠税0条、涉诉全部为原告。",
            "stability": "无经营异常、无股权冻结、无行政处罚。",
            "demand": "年盘子约 480 万（区间 400-560 万）。",
            "risk_signals": "红线 5 条全部未触发。",
            "monitoring": "监控回款逾期率，季度滚动评估。",
            "appendix": "数据采集日志、评分方法论、免责声明。",
        },
        "composite_score": 9.5,
        "credit_grade": "S",
        "recommended_credit_days": 44,
        "ar_days": 44,
        "credit_limit": 59,
    }


def _run_tests() -> None:
    passed = 0
    total = 0

    def check(label: str, cond: bool) -> None:
        nonlocal passed, total
        total += 1
        if cond:
            passed += 1
            print(f"  ✓ {label}")
        else:
            print(f"  ✗ {label}")

    # 测试 1: 合法报告通过
    check("合法报告通过", validate_report(_build_good_report()) == [])

    # 测试 2: 缺章节
    missing = _build_good_report()
    del missing["sections"]["financial"]
    check("缺章节失败", any("缺少章节 financial" in f for f in validate_report(missing)))

    # 测试 3: 占位符
    placeholder = _build_good_report()
    placeholder["sections"]["basic_info"] = "注册资本 XXX 万"
    check("占位符失败", any("含占位符" in f for f in validate_report(placeholder)))

    # 测试 4: 红线阻断报告通过
    blocked = _build_good_report()
    blocked["composite_score"] = None
    blocked["credit_grade"] = "D"
    blocked["recommended_credit_days"] = 0
    blocked["credit_limit"] = 0
    check("阻断报告通过", validate_report(blocked) == [])

    # 测试 5: 阻断但账期非 0
    bad_blocked = dict(blocked)
    bad_blocked["recommended_credit_days"] = 30
    check("阻断但账期非0失败", any("建议账期应为 0" in f for f in validate_report(bad_blocked)))

    # 测试 6: AR 硬约束
    ar_violation = _build_good_report()
    ar_violation["recommended_credit_days"] = 60
    ar_violation["ar_days"] = 44
    check("账期超应收周转失败", any("AR 硬约束" in f for f in validate_report(ar_violation)))

    print(f"\n{'✓' if passed == total else '✗'} 总计 {passed}/{total} 通过")
    if passed != total:
        sys.exit(1)


if __name__ == "__main__":
    main()
