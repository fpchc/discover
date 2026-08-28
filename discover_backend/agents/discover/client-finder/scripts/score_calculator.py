#!/usr/bin/env python3
"""八维评分计算脚本（P1）。

契约：stdin 一次写入 UTF-8 JSON，stdout 输出 UTF-8 JSON，非 0 退出码表示失败。
纯计算逻辑，不做数据获取与语义判断；同一输入永远得同一输出。
路径一律来自平台注入的环境变量或运行时计算，不含绝对路径字面量。

用法：
  echo '{"companies": [...]}' | python score_calculator.py
  python score_calculator.py '{"companies": [...]}'
"""

from __future__ import annotations

import json
import sys
from typing import Any

WEIGHTS: dict[str, float] = {
    "purchase_scale": 0.20,
    "tech_match": 0.20,
    "demand_intensity": 0.15,
    "purchase_timing": 0.15,
    "competitive_pos": 0.10,
    "reach_feasibility": 0.10,
    "decision_complex": 0.05,
    "credit_safety": 0.05,
}

CREDIT_SAFETY_MIN: float = 3.0
RESERVE_POOL_MIN: float = 4.0
SCORE_MIN: float = 0.0
SCORE_MAX: float = 10.0


def validate_input(companies: list[dict[str, Any]]) -> list[str]:
    """验证输入数据完整性，返回错误列表。"""
    errors: list[str] = []
    required_dims = set(WEIGHTS.keys())
    for i, company in enumerate(companies):
        name = str(company.get("company_name", f"#{i + 1}"))
        if "company_name" not in company:
            errors.append(f"第 {i + 1} 家企业缺少 company_name")
        scores = company.get("scores", {})
        if not isinstance(scores, dict):
            errors.append(f"{name} 缺少 scores")
            continue
        missing = required_dims - set(scores.keys())
        if missing:
            errors.append(f"{name}: 缺少维度 {sorted(missing)}")
        for dim, value in scores.items():
            if not isinstance(value, (int, float)):
                errors.append(f"{name}: {dim} = {value} 不是数值")
            elif value < SCORE_MIN or value > SCORE_MAX:
                errors.append(f"{name}: {dim} = {value} 超出范围 [{SCORE_MIN}, {SCORE_MAX}]")
    return errors


def check_red_flags(company: dict[str, Any]) -> tuple[bool, str]:
    """检查一票否决项，返回 (是否否决, 原因)。"""
    red_flags = company.get("red_flags", {})
    if not isinstance(red_flags, dict):
        return False, ""
    if red_flags.get("dishonesty"):
        return True, "失信被执行人"
    if red_flags.get("bankruptcy"):
        return True, "破产清算/破产重整"
    if red_flags.get("revoked"):
        return True, "经营状态为吊销/注销"
    if red_flags.get("severe_penalty"):
        return True, "严重行政处罚"
    return False, ""


def calculate_composite(scores: dict[str, Any]) -> float:
    """计算加权综合得分（0-10 保留两位）。"""
    total = 0.0
    for dim, weight in WEIGHTS.items():
        total += float(scores.get(dim, 0.0)) * weight
    return round(total, 2)


def process(companies: list[dict[str, Any]], top_n: int = 5) -> dict[str, Any]:
    """评分 → 排序 → 分类（推荐 / 排除 / 后备池）。"""
    recommended: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    reserve_pool: list[dict[str, Any]] = []

    for company in companies:
        name = company["company_name"]
        uscc = company.get("uscc", "")
        scores = company.get("scores", {})
        if not isinstance(scores, dict):
            scores = {}
        vetoed, veto_reason = check_red_flags(company)
        composite = calculate_composite(scores)
        if vetoed:
            excluded.append(
                {
                    "company_name": name,
                    "uscc": uscc,
                    "excluded_reason": veto_reason,
                    "composite_score": composite,
                }
            )
            continue
        credit = float(scores.get("credit_safety", 0))
        if credit < CREDIT_SAFETY_MIN:
            excluded.append(
                {
                    "company_name": name,
                    "uscc": uscc,
                    "excluded_reason": f"信用安全分 {credit} 低于阈值 {CREDIT_SAFETY_MIN}",
                    "composite_score": composite,
                }
            )
            continue
        entry: dict[str, Any] = {
            "company_name": name,
            "uscc": uscc,
            "composite_score": composite,
            "dimension_scores": scores,
        }
        if composite >= RESERVE_POOL_MIN:
            recommended.append(entry)
        else:
            reserve_pool.append(entry)

    recommended.sort(key=lambda x: float(x["composite_score"]), reverse=True)
    top_recommended = recommended[:top_n]
    remaining = recommended[top_n:] + reserve_pool
    for i, entry in enumerate(top_recommended):
        entry["rank"] = i + 1
        entry["status"] = "推荐"
    remaining.sort(key=lambda x: float(x["composite_score"]), reverse=True)
    for i, entry in enumerate(remaining):
        entry["rank"] = top_n + i + 1
        entry["status"] = "后备池"

    return {
        "rankings": top_recommended,
        "excluded": excluded,
        "reserve_pool": remaining,
        "summary": {
            "total_input": len(companies),
            "recommended": len(top_recommended),
            "excluded": len(excluded),
            "reserve_pool": len(remaining),
        },
    }


def _emit_error(message: str) -> None:
    print(json.dumps({"error": message}, ensure_ascii=False))
    sys.exit(1)


def main() -> None:
    raw = sys.argv[1] if len(sys.argv) > 1 else sys.stdin.read()
    try:
        data: dict[str, Any] = json.loads(raw)
    except json.JSONDecodeError as exc:
        _emit_error(f"JSON 解析失败: {exc}")
    companies = data.get("companies", [])
    top_n = int(data.get("top_n", 5))
    if not companies:
        _emit_error("companies 列表为空")
    if not isinstance(companies, list):
        _emit_error("companies 必须是数组")
    errors = validate_input(companies)
    if errors:
        _emit_error(f"输入验证失败: {'; '.join(errors)}")
    result = process(companies, top_n)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
