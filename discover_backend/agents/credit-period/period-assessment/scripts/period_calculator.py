#!/usr/bin/env python3
"""账期评估 — F/R/S 三因子加权评分计算器（P1）。

综合授信分 CS = w1·F(财务健康) + w2·R(信用风险) + w3·S(经营稳定性)
账期档位：90/60/45/30 天，叠加硬约束 建议账期 ≤ min(档位, 客户自身应收周转天数)
信用额度 M = (年盘子/12) * 账期月数 * 授信系数
红线门禁：任一触发 → 综合分置 None，标「阻断/现款现货」

契约：stdin 一次写入 UTF-8 JSON，stdout 输出 UTF-8 JSON，非 0 退出码表示失败。
纯计算逻辑，不做数据获取与语义判断；同一输入永远得同一输出。
路径一律来自平台注入的环境变量或运行时计算，不含绝对路径字面量。

用法：
  python period_calculator.py < input.json
  python period_calculator.py '{"items": [...]}'
  python period_calculator.py --test    # 冒烟测试
"""

from __future__ import annotations

import io
import json
import sys
from typing import Any

# 财务健康 F 子维度（满分合计 10）
F_SUB_DIMENSIONS: dict[str, dict[str, Any]] = {
    "偿债能力": {"max": 3.0, "说明": "负债率<40%且流动比>2→3; 40-60%且1-2→2; 60-80%→1; >80%或<1→0"},
    "盈利能力": {
        "max": 2.5,
        "说明": "毛利率>35%且净利率>15%→2.5; 25-35%或10-15%→2; 15-25%→1.5; <15%或亏损→1",
    },
    "现金流质量": {
        "max": 2.0,
        "说明": "OCF/营收>0.15且连续为正→2; 0.05-0.15→1.5; 0-0.05→1; OCF为负→0.5",
    },
    "增长势头": {
        "max": 1.5,
        "说明": "营收增速>30%且净利增速>50%→1.5; 15-30%→1; 0-15%→0.5; 负增长→0",
    },
    "营运效率": {"max": 1.0, "说明": "应收周转≤90天→1; ≤120天→0.5; >120天→0"},
}

# 信用风险 R（基础 10 分扣减）
R_BASE: float = 10.0
R_PENALTIES: dict[str, float] = {
    "在册被执行": 3.0,  # 每条 3 分，≥2 条归零
    "欠税/税务违法": 2.0,  # 每条 2 分
    "票据违约": 2.0,  # 每条 2 分
    "合同纠纷涉诉": 0.5,  # 每条 0.5 分，上限 3 分
}

# 经营稳定性 S（基础 10 分扣减）
S_BASE: float = 10.0
S_PENALTIES: dict[str, float] = {
    "经营异常在册": 5.0,
    "股权冻结": 3.0,
    "实控人变更": 2.0,
    "高管异常": 2.0,
    "行政处罚": 2.0,
    "审计非标": 5.0,
}

# 账期档位
CREDIT_TIERS: list[dict[str, Any]] = [
    {"min_cs": 8.5, "min_f": 8.0, "days": 90, "label": "90天账期"},
    {"min_cs": 7.0, "min_f": 6.5, "days": 60, "label": "60天账期"},
    {"min_cs": 5.5, "min_f": 0.0, "days": 45, "label": "45天账期"},
    {"min_cs": 4.0, "min_f": 0.0, "days": 30, "label": "30天账期"},
]

# 授信等级 → 授信系数（额度 = 月盘子 * 账期月数 * 系数）
CREDIT_FACTOR: dict[str, float] = {"S": 1.0, "A": 0.85, "B": 0.7, "C": 0.4, "D": 0.0}

# T1-T4 客户类型分层权重（非上市客户财报缺失，财务降权、信用+稳定升权）
TIER_WEIGHTS: dict[str, dict[str, Any]] = {
    "T1": {"F": 0.5, "R": 0.3, "S": 0.2, "label": "上市/大型"},
    "T2": {"F": 0.3, "R": 0.35, "S": 0.35, "label": "民营中型"},
    "T3": {"F": 0.2, "R": 0.45, "S": 0.35, "label": "贸易/小型"},
    "T4": {"F": 0.2, "R": 0.35, "S": 0.45, "label": "初创"},
}

# 非上市客户财务子维度强制中性分——盈利/现金流/增长三项财报不可得
NON_LISTED_NEUTRAL_DIMS: frozenset[str] = frozenset({"盈利能力", "现金流质量", "增长势头"})

# 红线门禁（布尔 → 中文标签）
RED_LINE_LABELS: dict[str, str] = {
    "dishonesty": "失信被执行人在册",
    "bankruptcy": "破产重整/吊销/注销",
    "serious_violation": "严重违法失信",
    "business_exception": "在册经营异常未移出",
    "cashflow_negative": "连续2年经营现金流+净利双负",
}

GRADE_LABELS: dict[str, str] = {
    "S": "S级 · 战略级 · 回款风险极低",
    "A": "A级 · 优选级 · 回款风险低",
    "B": "B级 · 合格级 · 回款风险可控",
    "C": "C级 · 观察级 · 回款风险需关注",
    "D": "D级 · 高风险 · 不建议账期合作",
}


def _num(value: object) -> float:
    """兼容 JSON 数值与缺失值，返回 float；非数值按 0 计。"""
    return float(value) if isinstance(value, (int, float)) else 0.0


def _classify(cs: float) -> str:
    """授信等级 S/A/B/C/D。"""
    if cs >= 8.5:
        return "S"
    if cs >= 7.0:
        return "A"
    if cs >= 5.5:
        return "B"
    if cs >= 4.0:
        return "C"
    return "D"


def _check_red_lines(item: dict[str, Any]) -> list[str]:
    """红线检测，返回触发的红线中文标签列表。"""
    red_lines = item.get("red_lines", {})
    if not isinstance(red_lines, dict):
        red_lines = {}
    return [label for key, label in RED_LINE_LABELS.items() if red_lines.get(key)]


def compute_period_score(item: dict[str, Any]) -> dict[str, Any]:
    """
    输入 item: 含 tier(T1-T4)、f_scores/r_penalties/s_penalties、ar_days、annual_spend、red_lines
    输出: 综合授信分 / 授信等级 / 建议账期 / 建议额度 / 红线状态
    """
    result: dict[str, Any] = {}

    # 客户类型分层（默认 T1 上市/大型）
    tier = str(item.get("tier", "T1"))
    weights = TIER_WEIGHTS.get(tier, TIER_WEIGHTS["T1"])
    is_listed = tier == "T1"
    result["tier"] = tier
    result["tier_label"] = str(weights["label"])

    # 1. 红线门禁
    triggered = _check_red_lines(item)
    result["red_line_triggered"] = triggered

    if triggered:
        result["composite_score"] = None
        result["credit_grade"] = "D"
        result["credit_grade_label"] = GRADE_LABELS["D"]
        result["recommended_credit_days"] = 0
        result["recommended_credit_days_label"] = "现款现货/30%预付"
        result["credit_limit"] = 0
        result["credit_limit_label"] = "无信用额度"
        result["status"] = "阻断"
        result["status_reason"] = "；".join(triggered)
        return result

    # 2. 财务健康 F（非上市客户盈利/现金流/增长三项强制中性分）
    f_scores = item.get("f_scores", {})
    if not isinstance(f_scores, dict):
        f_scores = {}
    f_total = 0.0
    for dim, spec in F_SUB_DIMENSIONS.items():
        max_val = float(spec["max"])
        if (not is_listed) and dim in NON_LISTED_NEUTRAL_DIMS:
            f_total += max_val * 0.5  # 非上市财报不可得，强制中性分
        else:
            f_total += _num(f_scores.get(dim)) if dim in f_scores else max_val * 0.5
    f = round(min(f_total, 10.0), 2)
    result["F"] = f

    # 3. 信用风险 R
    r_penalties = item.get("r_penalties", {})
    if not isinstance(r_penalties, dict):
        r_penalties = {}
    exec_count = _num(r_penalties.get("在册被执行"))
    if exec_count >= 2:
        r_score = 0.0
    else:
        r_score = R_BASE
        r_score -= exec_count * R_PENALTIES["在册被执行"]
        r_score -= _num(r_penalties.get("欠税/税务违法")) * R_PENALTIES["欠税/税务违法"]
        r_score -= _num(r_penalties.get("票据违约")) * R_PENALTIES["票据违约"]
        r_score -= min(_num(r_penalties.get("合同纠纷涉诉")) * R_PENALTIES["合同纠纷涉诉"], 3.0)
    r_score = round(max(r_score, 0.0), 2)
    result["R"] = r_score

    # 4. 经营稳定性 S
    s_penalties = item.get("s_penalties", {})
    if not isinstance(s_penalties, dict):
        s_penalties = {}
    s_score = S_BASE
    for dim, unit in S_PENALTIES.items():
        s_score -= _num(s_penalties.get(dim)) * unit
    s_score = round(max(s_score, 0.0), 2)
    result["S"] = s_score

    # 5. 综合授信分（按客户类型分层权重加权）
    w_f = float(weights["F"])
    w_r = float(weights["R"])
    w_s = float(weights["S"])
    cs = round(w_f * f + w_r * r_score + w_s * s_score, 2)
    result["composite_score"] = cs
    grade = _classify(cs)
    result["credit_grade"] = grade
    result["credit_grade_label"] = GRADE_LABELS[grade]
    result["weights"] = {"F": w_f, "R": w_r, "S": w_s}

    # 6. 账期档位（叠加 AR 硬约束）
    ar_days = int(_num(item.get("ar_days")) or 365)
    tier_days = 0
    for tier_spec in CREDIT_TIERS:
        if float(tier_spec["min_cs"]) <= cs and float(tier_spec["min_f"]) <= f:
            tier_days = int(tier_spec["days"])
            break
    if cs < 4.0:
        tier_days = 0
    recommended_days = min(tier_days, ar_days) if tier_days > 0 else 0
    result["ar_days"] = ar_days
    result["recommended_credit_days"] = recommended_days
    result["recommended_credit_days_label"] = (
        f"{recommended_days}天账期" if recommended_days > 0 else "现款现货/30%预付"
    )

    # 7. 信用额度
    annual_spend = _num(item.get("annual_spend"))
    monthly = annual_spend / 12.0
    months = recommended_days / 30.0
    factor = CREDIT_FACTOR[grade]
    credit_limit = round(monthly * months * factor, 0)
    result["annual_spend"] = annual_spend
    result["credit_limit"] = credit_limit
    result["credit_limit_label"] = f"{credit_limit:.0f} 万元" if credit_limit > 0 else "无信用额度"

    result["status"] = "通过"
    result["status_reason"] = "红线未触发，正常授信"
    return result


def validate_items(items: list[dict[str, Any]]) -> list[str]:
    """验证输入数据完整性，返回错误列表。"""
    errors: list[str] = []
    for i, item in enumerate(items):
        name = str(item.get("company_name", item.get("name", f"#{i + 1}")))
        if not name:
            errors.append(f"第 {i + 1} 项缺少 company_name")
        tier = item.get("tier", "T1")
        if tier not in TIER_WEIGHTS:
            errors.append(f"{name}: tier 非法 {tier!r}，须为 T1-T4")
    return errors


def run(data: dict[str, Any]) -> dict[str, Any]:
    """批量评分，返回统一结果结构。"""
    items = data.get("items", [])
    if not isinstance(items, list):
        items = []
    results: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("company_name", item.get("name", "")))
        score = compute_period_score(item)
        score["company_name"] = name
        results.append(score)
    return {"mode": "period-assessment", "total_items": len(results), "results": results}


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
    if not isinstance(data, dict):
        _emit_error("顶层必须是对象")
    items = data.get("items")
    if not isinstance(items, list) or not items:
        _emit_error("items 列表为空")
    errors = validate_items(items)
    if errors:
        _emit_error("输入验证失败: " + "; ".join(errors))
    result = run(data)
    print(json.dumps(result, ensure_ascii=False, indent=2))


# ═══════════════════════════════════════════════════════════
# 冒烟测试
# ═══════════════════════════════════════════════════════════


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

    # 测试 1: 优质上市客户（凯格精机场景，T1）
    good = {
        "company_name": "凯格精机",
        "tier": "T1",
        "f_scores": {
            "偿债能力": 3,
            "盈利能力": 2.5,
            "现金流质量": 1.0,
            "增长势头": 1.5,
            "营运效率": 1,
        },
        "r_penalties": {"在册被执行": 0, "欠税/税务违法": 0, "票据违约": 0, "合同纠纷涉诉": 0},
        "s_penalties": {},
        "ar_days": 44,
        "annual_spend": 480,
    }
    r = compute_period_score(good)
    check("优质客户 F=9.0", abs(float(r["F"]) - 9.0) < 0.01)
    check("优质客户 R 满分", abs(float(r["R"]) - 10.0) < 0.01)
    check("优质客户 CS=9.5", abs(float(r["composite_score"]) - 9.5) < 0.01)
    check("优质客户 S 级", r["credit_grade"] == "S")
    check("优质客户账期受 AR 约束", r["recommended_credit_days"] == 44)
    check("优质客户额度 59 万", abs(float(r["credit_limit"]) - 59.0) < 1.0)

    # 测试 2: 红线阻断
    red = {
        "company_name": "失信企业",
        "red_lines": {"dishonesty": True},
        "f_scores": {
            "偿债能力": 3,
            "盈利能力": 2.5,
            "现金流质量": 2,
            "增长势头": 1.5,
            "营运效率": 1,
        },
    }
    r = compute_period_score(red)
    check("红线触发状态阻断", r["status"] == "阻断")
    check("红线触发综合分为 None", r["composite_score"] is None)
    check("红线触发账期 0", r["recommended_credit_days"] == 0)
    check("红线触发额度 0", r["credit_limit"] == 0)

    # 测试 3: 多个被执行归零
    bad = {
        "company_name": "被执行企业",
        "r_penalties": {"在册被执行": 2, "欠税/税务违法": 0, "票据违约": 0, "合同纠纷涉诉": 3},
        "f_scores": {
            "偿债能力": 2,
            "盈利能力": 1.5,
            "现金流质量": 1,
            "增长势头": 0.5,
            "营运效率": 0.5,
        },
        "s_penalties": {},
        "ar_days": 60,
        "annual_spend": 800,
    }
    r = compute_period_score(bad)
    check("多个被执行 R 归零", abs(float(r["R"]) - 0.0) < 0.01)
    check("高风险客户 C/D 级", r["credit_grade"] in ("C", "D"))

    # 测试 4: 应收周转天数约束账期
    slow = dict(good)
    slow["ar_days"] = 200
    r = compute_period_score(slow)
    check("慢应收客户账期不超自身周转", r["recommended_credit_days"] <= 90)

    # 测试 5: T2 民营中型非上市——财务降级生效
    t2 = {
        "company_name": "非上市民营中型",
        "tier": "T2",
        "f_scores": {
            "偿债能力": 3,
            "盈利能力": 2.5,
            "现金流质量": 2,
            "增长势头": 1.5,
            "营运效率": 1,
        },
        "r_penalties": {"在册被执行": 0, "欠税/税务违法": 0, "票据违约": 0, "合同纠纷涉诉": 0},
        "s_penalties": {},
        "ar_days": 60,
        "annual_spend": 500,
    }
    r = compute_period_score(t2)
    # 盈利2.5→1.25、现金流2→1.0、增长1.5→0.75 三项强制中性；偿债3、营运1保留
    check("T2 非上市 F 强制降级=7.0", abs(float(r["F"]) - 7.0) < 0.01)
    expect = 0.3 * 7.0 + 0.35 * 10 + 0.35 * 10
    check("T2 权重生效(CS≠T1算法)", abs(float(r["composite_score"]) - expect) < 0.01)

    # 测试 6: T3 贸易/小型——信用为王权重
    t3 = {
        "company_name": "非上市贸易小型",
        "tier": "T3",
        "f_scores": {
            "偿债能力": 2,
            "盈利能力": 2.5,
            "现金流质量": 2,
            "增长势头": 1.5,
            "营运效率": 1,
        },
        "r_penalties": {"在册被执行": 0, "欠税/税务违法": 0, "票据违约": 0, "合同纠纷涉诉": 0},
        "s_penalties": {},
        "ar_days": 30,
        "annual_spend": 200,
    }
    r = compute_period_score(t3)
    expect_f = 2 + 1.25 + 1.0 + 0.75 + 1  # = 6.0
    check("T3 非上市 F=6.0", abs(float(r["F"]) - expect_f) < 0.01)
    expect = 0.2 * expect_f + 0.45 * 10 + 0.35 * 10
    check("T3 权重 0.2/0.45/0.35", abs(float(r["composite_score"]) - expect) < 0.01)

    print(f"\n{'✓' if passed == total else '✗'} 总计 {passed}/{total} 通过")
    if passed != total:
        sys.exit(1)


if __name__ == "__main__":
    main()
