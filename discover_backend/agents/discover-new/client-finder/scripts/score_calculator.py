#!/usr/bin/env python3
"""八维评分计算器（V3 准确性优先版，含 Score Trace）。

契约：stdin 一次写入 UTF-8 JSON，stdout 输出 UTF-8 JSON，非 0 退出码表示失败。
纯计算逻辑：八维加权综合分 + 红线一票否决 + 排序，不做数据获取与语义判断；
同一输入永远得同一输出。

Score Trace：每维分数可附 score_trace[dim] = {basis, source}，脚本原样回显，
使最终综合分可反推每一维依据（供 Final QA 核对「评分与证据一致」）。

用法：
  echo '{"companies":[...],"top_n":1}' | python score_calculator.py
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
RED_FLAGS: tuple[str, ...] = ("dishonesty", "bankruptcy", "revoked", "severe_penalty")
RED_FLAG_REASON: dict[str, str] = {
    "dishonesty": "失信被执行人",
    "bankruptcy": "破产清算/破产重整",
    "revoked": "经营状态为吊销/注销",
    "severe_penalty": "严重行政处罚",
}


def composite(scores: dict[str, Any]) -> float:
    """计算加权综合得分（0-10 保留两位）。"""
    return round(sum(float(scores.get(dim, 0.0)) * w for dim, w in WEIGHTS.items()), 2)


def veto_reason(flags: dict[str, Any]) -> str | None:
    """检查一票否决项，返回原因；无则返回 None。"""
    for flag in RED_FLAGS:
        if bool(flags.get(flag)):
            return RED_FLAG_REASON[flag]
    return None


def process(companies: list[dict[str, Any]], top_n: int) -> dict[str, Any]:
    """评分 → 排序 → 分类（推荐 / 排除）。"""
    recommended: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for company in companies:
        name = str(company.get("company_name", "?"))
        scores = company.get("scores") or {}
        flags = company.get("red_flags") or {}
        reason = veto_reason(flags)
        if reason is not None:
            excluded.append({"company_name": name, "reason": f"红线一票否决：{reason}"})
        elif float(scores.get("credit_safety", 0.0)) < CREDIT_SAFETY_MIN:
            credit = scores.get("credit_safety")
            reason = f"信用安全分 {credit} 低于阈值 {CREDIT_SAFETY_MIN}"
            excluded.append({"company_name": name, "reason": reason})
        else:
            recommended.append(
                {
                    "company_name": name,
                    "uscc": str(company.get("uscc", "")),
                    "composite_score": composite(scores),
                    "dimension_scores": scores,
                    "score_trace": company.get("score_trace") or {},
                }
            )
    recommended.sort(key=lambda x: float(x["composite_score"]), reverse=True)
    for i, entry in enumerate(recommended[:top_n]):
        entry["rank"] = i + 1
    return {
        "recommended": recommended[:top_n],
        "rest": recommended[top_n:],
        "excluded": excluded,
    }


def main() -> None:
    raw = sys.stdin.read()
    try:
        data: dict[str, Any] = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(json.dumps({"error": f"JSON 解析失败: {exc}"}, ensure_ascii=False))
        sys.exit(1)
    companies = data.get("companies", [])
    if not isinstance(companies, list) or not companies:
        print(json.dumps({"error": "companies 必须是非空数组"}, ensure_ascii=False))
        sys.exit(1)
    top_n = int(data.get("top_n", 1))
    print(json.dumps(process(companies, top_n), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
