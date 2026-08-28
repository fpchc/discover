#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PCB 客户账期评估 — 账期授信模型计算器

综合授信分 CS = 0.5·F(财务健康) + 0.3·R(信用风险) + 0.2·S(经营稳定性)
账期档位：90/60/45/30 天，叠加硬约束 建议账期 ≤ min(档位, 客户自身应收周转天数)
信用额度 M = (PCB年盘子P/12) × 账期月数 × 授信系数
红线门禁：任一触发 → 综合分置 None，标"阻断/现金交易"

输入：JSON（stdin 或 SCORE_INPUT_FILE 环境变量）
输出：评分结果 JSON（stdout 或 SCORE_OUTPUT_FILE 环境变量）
用法：
  python credit_calculator.py < input.json
  python credit_calculator.py --test     # 跑冒烟测试
"""

import json
import os
import sys

# ═══════════════════════════════════════════════════════════
# 账期量化模型核心
# ═══════════════════════════════════════════════════════════

# 财务健康 F 子维度（满分合计 10）
F_SUB_DIMENSIONS = {
    "偿债能力": {"max": 3, "说明": "负债率<40%且流动比>2→3; 40-60%且1-2→2; 60-80%→1; >80%或<1→0"},
    "盈利能力": {"max": 2.5, "说明": "毛利率>35%且净利率>15%→2.5; 25-35%或10-15%→2; 15-25%→1.5; <15%或亏损→1"},
    "现金流质量": {"max": 2, "说明": "OCF/营收>0.15且连续为正→2; 0.05-0.15→1.5; 0-0.05→1; OCF为负→0.5"},
    "增长势头": {"max": 1.5, "说明": "营收增速>30%且净利增速>50%→1.5; 15-30%→1; 0-15%→0.5; 负增长→0"},
    "营运效率": {"max": 1, "说明": "应收周转≤90天→1; ≤120天→0.5; >120天→0"},
}

# 信用风险 R（基础 10 分扣减）
R_BASE = 10
R_PENALTIES = {
    "在册被执行": 3,        # 每条 3 分，≥2 条归零
    "欠税/税务违法": 2,     # 每条 2 分
    "票据违约": 2,          # 每条 2 分
    "合同纠纷涉诉": 0.5,    # 每条 0.5 分，上限 3 分
}

# 经营稳定性 S（基础 10 分扣减）
S_BASE = 10
S_PENALTIES = {
    "经营异常在册": 5,
    "股权冻结": 3,
    "实控人变更": 2,
    "高管异常": 2,
    "行政处罚": 2,
    "审计非标": 5,
}

# 账期档位
CREDIT_TIERS = [
    {"min_cs": 8.5, "min_f": 8.0, "days": 90, "label": "90天账期"},
    {"min_cs": 7.0, "min_f": 6.5, "days": 60, "label": "60天账期"},
    {"min_cs": 5.5, "min_f": 0, "days": 45, "label": "45天账期"},
    {"min_cs": 4.0, "min_f": 0, "days": 30, "label": "30天账期"},
]

# 授信等级 → 授信系数（额度 = 月盘子 × 账期月数 × 系数）
CREDIT_FACTOR = {"S": 1.0, "A": 0.85, "B": 0.7, "C": 0.4, "D": 0.0}

# ═══════════════════════════════════════════════════════════
# T1-T4 客户类型分层权重（CS = w1·F + w2·R + w3·S）
# 不同客户类型自动切换财务/信用/稳定性权重——非上市客户财报缺失，
# 财务权重应下调，信用风险与经营稳定性权重应上调。
# ═══════════════════════════════════════════════════════════

TIER_WEIGHTS = {
    "T1": {"F": 0.5, "R": 0.3, "S": 0.2, "label": "上市/大型"},
    "T2": {"F": 0.3, "R": 0.35, "S": 0.35, "label": "民营中型"},
    "T3": {"F": 0.2, "R": 0.45, "S": 0.35, "label": "贸易/小型"},
    "T4": {"F": 0.2, "R": 0.35, "S": 0.45, "label": "初创"},
}

# 非上市客户财务子维度强制取中性分的维度——盈利/现金流/增长三项财报不可得
NON_LISTED_NEUTRAL_DIMS = {"盈利能力", "现金流质量", "增长势头"}

# 红线门禁（二进制）
RED_LINES = [
    "失信被执行人在册",
    "破产重整/吊销/注销",
    "严重违法失信",
    "在册经营异常未移出",
    "连续2年经营现金流+净利双负",
]


def _classify(cs):
    """授信等级 S/A/B/C/D。"""
    if cs is None:
        return "D"
    if cs >= 8.5:
        return "S"
    if cs >= 7.0:
        return "A"
    if cs >= 5.5:
        return "B"
    if cs >= 4.0:
        return "C"
    return "D"


def _check_red_lines(item):
    """红线检测，返回 (触发列表, 阻断原因)。"""
    triggered = []
    for rl in RED_LINES:
        if item.get(rl, False):
            triggered.append(rl)
    return triggered, "；".join(triggered)


def compute_credit_score(item):
    """
    输入 item: 含 tier(T1-T4)、F/R/S 子分、AR 应收周转天数、P PCB年盘子、红线状态
    输出: 完整评分结果
    """
    result = {}

    # 客户类型分层（默认 T1 上市/大型）
    tier = item.get("tier", "T1")
    weights = TIER_WEIGHTS.get(tier, TIER_WEIGHTS["T1"])
    is_listed = (tier == "T1")
    result["tier"] = tier
    result["tier_label"] = weights["label"]

    # 1. 红线门禁
    triggered, reason = _check_red_lines(item)
    result["red_line_triggered"] = triggered

    if triggered:
        result["composite_score"] = None
        result["credit_grade"] = "D"
        result["credit_grade_label"] = "阻断 · 现金交易/30%预付"
        result["recommended_credit_days"] = 0
        result["recommended_credit_days_label"] = "现款现货/30%预付"
        result["credit_limit"] = 0
        result["credit_limit_label"] = "无信用额度"
        result["status"] = "阻断"
        result["status_reason"] = reason
        return result

    # 2. 财务健康 F（非上市客户盈利/现金流/增长三项强制中性分）
    f_scores = item.get("f_scores", {})
    F = 0.0
    for dim, spec in F_SUB_DIMENSIONS.items():
        if (not is_listed) and dim in NON_LISTED_NEUTRAL_DIMS:
            F += spec["max"] * 0.5  # 非上市财报不可得，强制中性分
        else:
            F += f_scores.get(dim, spec["max"] * 0.5)  # 缺失按 50% 计
    F = round(min(F, 10.0), 2)
    result["F"] = F

    # 3. 信用风险 R
    r_penalties = item.get("r_penalties", {})
    R = R_BASE
    if r_penalties.get("在册被执行", 0) >= 2:
        R = 0
    else:
        R -= r_penalties.get("在册被执行", 0) * R_PENALTIES["在册被执行"]
        R -= r_penalties.get("欠税/税务违法", 0) * R_PENALTIES["欠税/税务违法"]
        R -= r_penalties.get("票据违约", 0) * R_PENALTIES["票据违约"]
        R -= min(r_penalties.get("合同纠纷涉诉", 0) * R_PENALTIES["合同纠纷涉诉"], 3.0)
    R = round(max(R, 0.0), 2)
    result["R"] = R

    # 4. 经营稳定性 S
    s_penalties = item.get("s_penalties", {})
    S = S_BASE
    for dim, val in s_penalties.items():
        S -= val * S_PENALTIES.get(dim, 0)
    S = round(max(S, 0.0), 2)
    result["S"] = S

    # 5. 综合授信分（按客户类型分层权重加权）
    CS = round(weights["F"] * F + weights["R"] * R + weights["S"] * S, 2)
    result["composite_score"] = CS
    result["credit_grade"] = _classify(CS)
    result["credit_grade_label"] = {
        "S": "S级 · 战略级 · 回款风险极低",
        "A": "A级 · 优选级 · 回款风险低",
        "B": "B级 · 合格级 · 回款风险可控",
        "C": "C级 · 观察级 · 回款风险需关注",
        "D": "D级 · 高风险 · 不建议账期合作",
    }[result["credit_grade"]]

    # 6. 账期档位（叠加 AR 硬约束）
    ar_days = item.get("ar_days", 365)  # 客户自身应收周转天数
    tier_days = 0
    for tier in CREDIT_TIERS:
        if CS >= tier["min_cs"] and F >= tier["min_f"]:
            tier_days = tier["days"]
            break
    if CS < 4.0:
        tier_days = 0
    recommended_days = min(tier_days, ar_days) if tier_days > 0 else 0
    result["ar_days"] = ar_days
    result["recommended_credit_days"] = recommended_days
    result["recommended_credit_days_label"] = (
        f"{recommended_days}天账期" if recommended_days > 0 else "现款现货/30%预付"
    )

    # 7. 信用额度
    p_annual = item.get("pcb_annual_spend", 0)  # PCB 年盘子（万元）
    monthly = p_annual / 12.0
    months = recommended_days / 30.0
    factor = CREDIT_FACTOR[result["credit_grade"]]
    credit_limit = round(monthly * months * factor, 0)
    result["pcb_annual_spend"] = p_annual
    result["credit_limit"] = credit_limit
    result["credit_limit_label"] = f"{credit_limit:.0f} 万元" if credit_limit > 0 else "无信用额度"

    result["status"] = "通过"
    result["status_reason"] = "红线未触发，正常授信"
    return result


def run(data):
    items = data.get("items", [])
    results = []
    for item in items:
        name = item.get("name", item.get("company_name", ""))
        r = compute_credit_score(item)
        r["name"] = name
        results.append(r)
    return {
        "mode": "credit-assessment",
        "total_items": len(items),
        "results": results,
    }


def main():
    # Windows 控制台默认 GBK，统一重定向 stdout 为 UTF-8 避免 ✓/中文打印报错
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    if "--test" in sys.argv:
        _run_tests()
        return

    # 优先用文件路径参数，避免 Windows stdin 编码歧义
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) >= 1:
        in_file = args[0]
        out_file = args[1] if len(args) >= 2 else None
    else:
        in_file = os.environ.get("SCORE_INPUT_FILE")
        out_file = os.environ.get("SCORE_OUTPUT_FILE")

    if in_file:
        with open(in_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        raw = sys.stdin.buffer.read().decode("utf-8")
        data = json.loads(raw)

    output = run(data)
    json_str = json.dumps(output, ensure_ascii=False, indent=2)

    if out_file:
        with open(out_file, "w", encoding="utf-8") as f:
            f.write(json_str)
        print(f"Output written to {out_file}")
    else:
        sys.stdout.buffer.write(json_str.encode("utf-8"))


# ═══════════════════════════════════════════════════════════
# 冒烟测试
# ═══════════════════════════════════════════════════════════

def _run_tests():
    passed = 0
    total = 0

    def check(label, cond):
        nonlocal passed, total
        total += 1
        if cond:
            passed += 1
            print(f"  ✓ {label}")
        else:
            print(f"  ✗ {label}")

    # 测试 1: 优质客户（凯格精机场景）
    good = {
        "name": "凯格精机",
        "f_scores": {"偿债能力": 3, "盈利能力": 2.5, "现金流质量": 1.5, "增长势头": 1.5, "营运效率": 1},
        "r_penalties": {"在册被执行": 0, "欠税/税务违法": 0, "票据违约": 0, "合同纠纷涉诉": 0},
        "s_penalties": {},
        "ar_days": 44,
        "pcb_annual_spend": 1500,
    }
    r = compute_credit_score(good)
    check("优质客户 F 满分", abs(r["F"] - 9.5) < 0.01)
    check("优质客户 R 满分", abs(r["R"] - 10.0) < 0.01)
    check("优质客户 CS 高", r["composite_score"] >= 8.5)
    check("优质客户 S 级", r["credit_grade"] == "S")
    check("优质客户账期受 AR 约束", r["recommended_credit_days"] == 44)
    check("优质客户有额度", r["credit_limit"] > 0)

    # 测试 2: 红线阻断
    red = {
        "name": "失信企业",
        "失信被执行人在册": True,
        "f_scores": {"偿债能力": 3, "盈利能力": 2.5, "现金流质量": 2, "增长势头": 1.5, "营运效率": 1},
    }
    r = compute_credit_score(red)
    check("红线触发状态阻断", r["status"] == "阻断")
    check("红线触发综合分为 None", r["composite_score"] is None)
    check("红线触发账期 0", r["recommended_credit_days"] == 0)

    # 测试 3: 多个被执行归零
    bad = {
        "name": "被执行企业",
        "r_penalties": {"在册被执行": 2, "欠税/税务违法": 0, "票据违约": 0, "合同纠纷涉诉": 3},
        "f_scores": {"偿债能力": 2, "盈利能力": 1.5, "现金流质量": 1, "增长势头": 0.5, "营运效率": 0.5},
        "s_penalties": {},
        "ar_days": 60,
        "pcb_annual_spend": 800,
    }
    r = compute_credit_score(bad)
    check("多个被执行 R 归零", abs(r["R"] - 0.0) < 0.01)
    check("高风险客户 C/D 级", r["credit_grade"] in ("C", "D"))

    # 测试 4: 应收周转天数约束账期
    slow = dict(good)
    slow["ar_days"] = 200
    r = compute_credit_score(slow)
    check("慢应收客户账期不超自身周转", r["recommended_credit_days"] <= 90)

    # 测试 5: T1 上市客户（凯格真实数据）结果不变验证
    kaige_t1 = {
        "name": "凯格精机",
        "tier": "T1",
        "f_scores": {"偿债能力": 3, "盈利能力": 2.5, "现金流质量": 1.0, "增长势头": 1.5, "营运效率": 1},
        "r_penalties": {"在册被执行": 0, "欠税/税务违法": 0, "票据违约": 0, "合同纠纷涉诉": 0},
        "s_penalties": {},
        "ar_days": 44,
        "pcb_annual_spend": 480,
    }
    r = compute_credit_score(kaige_t1)
    check("T1 凯格 F=9.0", abs(r["F"] - 9.0) < 0.01)
    check("T1 凯格 CS=9.5", abs(r["composite_score"] - 9.5) < 0.01)
    check("T1 凯格 S级", r["credit_grade"] == "S")
    check("T1 凯格额度 59万", abs(r["credit_limit"] - 59.0) < 1.0)

    # 测试 6: T2 民营中型非上市——财务降级生效
    t2 = {
        "name": "非上市民营中型",
        "tier": "T2",
        "f_scores": {"偿债能力": 3, "盈利能力": 2.5, "现金流质量": 2, "增长势头": 1.5, "营运效率": 1},
        "r_penalties": {"在册被执行": 0, "欠税/税务违法": 0, "票据违约": 0, "合同纠纷涉诉": 0},
        "s_penalties": {},
        "ar_days": 60,
        "pcb_annual_spend": 500,
    }
    r = compute_credit_score(t2)
    # 盈利2.5→1.25、现金流2→1.0、增长1.5→0.75 三项强制中性；偿债3、营运1保留
    check("T2 非上市 F 强制降级=7.0", abs(r["F"] - 7.0) < 0.01)
    check("T2 权重生效(CS≠T1算法)", abs(r["composite_score"] - (0.3*7.0 + 0.35*10 + 0.35*10)) < 0.01)

    # 测试 7: T3 贸易/小型非上市——信用为王权重
    t3 = {
        "name": "非上市贸易小型",
        "tier": "T3",
        "f_scores": {"偿债能力": 2, "盈利能力": 2.5, "现金流质量": 2, "增长势头": 1.5, "营运效率": 1},
        "r_penalties": {"在册被执行": 0, "欠税/税务违法": 0, "票据违约": 0, "合同纠纷涉诉": 0},
        "s_penalties": {},
        "ar_days": 30,
        "pcb_annual_spend": 200,
    }
    r = compute_credit_score(t3)
    # 偿债2保留，盈利/现金流/增长强制中性
    expect_f = 2 + 1.25 + 1.0 + 0.75 + 1  # = 6.0
    check("T3 非上市 F=6.0", abs(r["F"] - expect_f) < 0.01)
    check("T3 权重 0.2/0.45/0.35", abs(r["composite_score"] - (0.2*expect_f + 0.45*10 + 0.35*10)) < 0.01)

    print(f"\n{'✓' if passed == total else '✗'} 总计 {passed}/{total} 通过")


if __name__ == "__main__":
    main()
