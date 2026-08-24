#!/usr/bin/env python3
"""
EITIA 客户发现 Skill — 八维评分计算脚本

功能：给定 8 个维度的原始观测数据，计算综合得分、排名和一票否决判定。
输入：JSON（stdin 或命令行参数）
输出：JSON（stdout）

设计原则：
- 纯计算逻辑，不做数据获取和语义判断
- 确定性：同一输入永远得同一输出
- 边界保护：输入验证 + 异常处理

用法：
  echo '{"companies": [...]}' | python score_calculator.py
  python score_calculator.py '{"companies": [...]}'
"""

import json
import sys
from typing import Any


# === 配置 ===

# 维度权重（总和 = 1.0）
WEIGHTS = {
    "purchase_scale":    0.20,   # 维度1：采购规模
    "tech_match":        0.20,   # 维度2：技术匹配
    "demand_intensity":  0.15,   # 维度3：需求强度
    "purchase_timing":   0.15,   # 维度4：采购时机
    "competitive_pos":   0.10,   # 维度5：竞争位置
    "reach_feasibility": 0.10,   # 维度6：触达可行性
    "decision_complex":  0.05,   # 维度7：决策复杂度
    "credit_safety":     0.05,   # 维度8：信用安全
}

# 一票否决的最低信用安全阈值
CREDIT_SAFETY_MIN = 3.0

# 后备池最低综合分阈值
RESERVE_POOL_MIN = 4.0

# 所有维度的有效范围
SCORE_MIN = 0.0
SCORE_MAX = 10.0

# === 数据结构定义 ===

"""
输入 JSON 格式：
{
    "companies": [
        {
            "company_name": "锐捷网络股份有限公司",
            "uscc": "913501007267123456",
            "scores": {
                "purchase_scale": 8.0,
                "tech_match": 9.0,
                "demand_intensity": 7.0,
                "purchase_timing": 7.5,
                "competitive_pos": 6.0,
                "reach_feasibility": 8.0,
                "decision_complex": 4.0,
                "credit_safety": 9.0
            },
            "red_flags": {
                "dishonesty": false,
                "bankruptcy": false,
                "revoked": false,
                "severe_penalty": false
            }
        }
    ],
    "top_n": 5
}

输出 JSON 格式：
{
    "rankings": [
        {
            "rank": 1,
            "company_name": "锐捷网络股份有限公司",
            "uscc": "913501007267123456",
            "composite_score": 7.63,
            "dimension_scores": {...},
            "status": "推荐",
            "excluded_reason": null
        }
    ],
    "excluded": [...],
    "reserve_pool": [...],
    "summary": {
        "total_input": 10,
        "recommended": 5,
        "excluded": 1,
        "reserve_pool": 4
    }
}
"""


def validate_input(companies: list[dict]) -> list[str]:
    """验证输入数据完整性，返回错误列表"""
    errors = []
    required_dims = set(WEIGHTS.keys())

    for i, company in enumerate(companies):
        name = company.get("company_name", f"#{i+1}")
        scores = company.get("scores", {})

        # 检查必填字段
        if "company_name" not in company:
            errors.append(f"第 {i+1} 家企业缺少 company_name")

        if "scores" not in company:
            errors.append(f"{name} 缺少 scores")
            continue

        # 检查维度完整性
        missing = required_dims - set(scores.keys())
        if missing:
            errors.append(f"{name}: 缺少维度 {missing}")

        # 检查分值范围
        for dim, value in scores.items():
            if not isinstance(value, (int, float)):
                errors.append(f"{name}: {dim} = {value} 不是数值")
            elif value < SCORE_MIN or value > SCORE_MAX:
                errors.append(f"{name}: {dim} = {value} 超出范围 [{SCORE_MIN}, {SCORE_MAX}]")

    return errors


def check_red_flags(company: dict) -> tuple[bool, str]:
    """
    检查一票否决项。
    返回：(是否被否决, 否决原因)
    """
    red_flags = company.get("red_flags", {})

    if red_flags.get("dishonesty"):
        return True, "失信被执行人"

    if red_flags.get("bankruptcy"):
        return True, "破产清算/破产重整"

    if red_flags.get("revoked"):
        return True, "经营状态为吊销/注销"

    if red_flags.get("severe_penalty"):
        return True, "严重行政处罚"

    return False, ""


def calculate_composite(scores: dict[str, float]) -> float:
    """计算加权综合得分"""
    total = 0.0
    for dim, weight in WEIGHTS.items():
        total += scores.get(dim, 0.0) * weight
    return round(total, 2)


def process(companies: list[dict], top_n: int = 5) -> dict:
    """
    主处理函数：评分 → 排序 → 分类。

    返回结构化的排名结果，包含：
    - rankings: TOP N 推荐企业
    - excluded: 被一票否决排除的企业
    - reserve_pool: 后备池企业
    """

    recommended = []
    excluded = []
    reserve_pool = []

    for company in companies:
        name = company["company_name"]
        uscc = company.get("uscc", "")
        scores = company.get("scores", {})

        # 1. 一票否决检查
        vetoed, veto_reason = check_red_flags(company)
        if vetoed:
            excluded.append({
                "company_name": name,
                "uscc": uscc,
                "excluded_reason": veto_reason,
                "composite_score": calculate_composite(scores),
            })
            continue

        # 2. 信用安全阈值检查
        credit = scores.get("credit_safety", 0)
        if credit < CREDIT_SAFETY_MIN:
            excluded.append({
                "company_name": name,
                "uscc": uscc,
                "excluded_reason": f"信用安全分 {credit} 低于阈值 {CREDIT_SAFETY_MIN}",
                "composite_score": calculate_composite(scores),
            })
            continue

        # 3. 计算综合分
        composite = calculate_composite(scores)

        entry = {
            "company_name": name,
            "uscc": uscc,
            "composite_score": composite,
            "dimension_scores": scores,
        }

        # 4. 分类
        if composite >= RESERVE_POOL_MIN:
            recommended.append(entry)
        else:
            reserve_pool.append(entry)

    # 5. 排序
    recommended.sort(key=lambda x: x["composite_score"], reverse=True)

    # 6. 分割 TOP N 和后备池
    top_recommended = recommended[:top_n]
    remaining = recommended[top_n:] + reserve_pool

    # 添加排名
    for i, entry in enumerate(top_recommended):
        entry["rank"] = i + 1
        entry["status"] = "推荐"

    # 后备池排序
    remaining.sort(key=lambda x: x["composite_score"], reverse=True)
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


def main():
    # 解析输入
    if len(sys.argv) > 1:
        raw = sys.argv[1]
    else:
        raw = sys.stdin.read()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"JSON 解析失败: {str(e)}"}, ensure_ascii=False))
        sys.exit(1)

    companies = data.get("companies", [])
    top_n = data.get("top_n", 5)

    if not companies:
        print(json.dumps({"error": "companies 列表为空"}, ensure_ascii=False))
        sys.exit(1)

    # 验证
    errors = validate_input(companies)
    if errors:
        print(json.dumps({"error": "输入验证失败", "details": errors}, ensure_ascii=False))
        sys.exit(1)

    # 处理
    result = process(companies, top_n)

    # 输出
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
