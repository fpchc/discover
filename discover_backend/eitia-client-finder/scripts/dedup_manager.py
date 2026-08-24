#!/usr/bin/env python3
"""
EITIA 客户发现 Skill — 去重管理脚本

功能：
1. 管理推荐历史缓存文件（recommendation-history.json）
2. 计算新输入与历史线索的相似度
3. 生成排除列表（已推荐 + 后备池中企业）
4. 计算后备池激活优先级

输入：JSON（stdin 或命令行参数）
输出：JSON（stdout）

用法：
  echo '{"mode": "match", ...}' | python dedup_manager.py

模式：
- match：匹配当前输入与历史线索
- exclude：生成排除列表
- add：添加新的推荐记录
- activate：计算后备池激活排序
"""

import json
import os
import sys
from pathlib import Path
from typing import Any


# === 配置 ===

# 缓存文件路径（相对于 skill 目录）
CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache"
CACHE_FILE = CACHE_DIR / "recommendation-history.json"

# 相似度阈值
SIMILARITY_THRESHOLD = 0.7

# 相似度权重
KEYWORD_WEIGHT = 0.6   # 产品关键词 Jaccard 相似度
INDUSTRY_WEIGHT = 0.4  # 目标行业匹配度


# === 工具函数 ===

def load_cache() -> dict:
    """加载缓存文件"""
    if not CACHE_FILE.exists():
        return {"version": "1.0", "product_clues": []}
    with open(CACHE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_cache(data: dict) -> None:
    """保存缓存文件"""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def jaccard_similarity(set_a: set, set_b: set) -> float:
    """计算 Jaccard 相似度"""
    if not set_a or not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union > 0 else 0.0


def normalize_keywords(keywords: list[str]) -> set[str]:
    """标准化关键词集合"""
    return set(k.strip().lower() for k in keywords if k.strip())


# === 核心功能 ===

def match_clue(product_keywords: list[str], target_industry: str = "") -> dict | None:
    """
    匹配当前输入与历史线索。

    返回：最匹配的历史线索（相似度 ≥ 阈值），或 None。
    """
    cache = load_cache()
    input_keywords = normalize_keywords(product_keywords)
    input_industry_lower = target_industry.strip().lower()

    best_match = None
    best_similarity = 0.0

    for clue in cache.get("product_clues", []):
        clue_keywords = normalize_keywords(clue.get("product_keywords", []))
        clue_industry = clue.get("target_industry", "").strip().lower()

        # 关键词 Jaccard 相似度
        kw_sim = jaccard_similarity(input_keywords, clue_keywords)

        # 行业匹配度
        if not input_industry_lower or not clue_industry:
            ind_sim = 0.5  # 行业信息不完整时取中性值
        elif input_industry_lower == clue_industry:
            ind_sim = 1.0
        elif input_industry_lower in clue_industry or clue_industry in input_industry_lower:
            ind_sim = 0.8
        else:
            ind_sim = 0.0

        # 加权综合相似度
        similarity = kw_sim * KEYWORD_WEIGHT + ind_sim * INDUSTRY_WEIGHT

        if similarity >= SIMILARITY_THRESHOLD and similarity > best_similarity:
            best_similarity = similarity
            best_match = clue

    return best_match


def generate_exclude_lists(product_keywords: list[str], target_industry: str = "") -> dict:
    """
    生成排除列表（已推荐企业 + 后备池企业）。

    返回：{"recommended": [...], "reserve_pool": [...], "all_excluded": [...], "matched_clue": ...}
    """
    matched = match_clue(product_keywords, target_industry)

    if not matched:
        return {
            "matched": False,
            "recommended": [],
            "reserve_pool": [],
            "all_excluded": [],
            "matched_clue": None,
        }

    recommended = []
    reserve_pool = []
    all_excluded = []

    for rec in matched.get("recommendations", []):
        company_name = rec.get("company_name", "")
        uscc = rec.get("uscc", "")
        status = rec.get("status", "")

        entry = {"company_name": company_name, "uscc": uscc, "status": status}

        if status == "已推荐":
            recommended.append(entry)
        elif status == "后备池":
            reserve_pool.append(entry)

        all_excluded.append(entry)

    # 加上手动排除的企业
    for name in matched.get("excluded_companies", []):
        all_excluded.append({"company_name": name, "uscc": "", "status": "手动排除"})

    return {
        "matched": True,
        "matched_clue": {
            "clue_id": matched.get("clue_id", ""),
            "created_at": matched.get("created_at", ""),
            "total_found": matched.get("total_found", 0),
            "remaining_pool": matched.get("remaining_pool", 0),
        },
        "recommended": recommended,
        "reserve_pool": reserve_pool,
        "all_excluded": all_excluded,
        "similarity": match_clue(product_keywords, target_industry),  # 保存相似度信息
    }


def add_recommendations(clue_data: dict) -> dict:
    """
    添加新的推荐记录到缓存。

    clue_data 格式：
    {
        "product_keywords": ["高速背板连接器"],
        "target_industry": "数据中心交换机",
        "report_path": "D:/.../xxx.pdf",
        "recommendations": [
            {"company_name": "...", "uscc": "...", "rank": 1, "score": 8.7, "status": "已推荐"},
            ...
        ],
        "excluded_companies": []
    }
    """
    cache = load_cache()

    # 生成 clue_id
    import datetime
    today = datetime.date.today().strftime("%Y%m%d")
    product_key = "_".join(clue_data.get("product_keywords", ["unknown"])[:2])
    clue_id = f"{product_key}_{today}"

    # 检查是否已存在相同 clue_id
    existing = None
    for i, clue in enumerate(cache.get("product_clues", [])):
        if clue.get("clue_id") == clue_id:
            existing = i
            break

    new_clue = {
        "clue_id": clue_id,
        "product_keywords": clue_data.get("product_keywords", []),
        "target_industry": clue_data.get("target_industry", ""),
        "created_at": datetime.datetime.now().isoformat(),
        "report_path": clue_data.get("report_path", ""),
        "recommendations": clue_data.get("recommendations", []),
        "excluded_companies": clue_data.get("excluded_companies", []),
        "total_found": len([r for r in clue_data.get("recommendations", []) if r.get("status") == "已推荐"]),
        "remaining_pool": len([r for r in clue_data.get("recommendations", []) if r.get("status") == "后备池"]),
    }

    if existing is not None:
        cache["product_clues"][existing] = new_clue
    else:
        cache.setdefault("product_clues", []).append(new_clue)

    save_cache(cache)

    return {"success": True, "clue_id": clue_id, "action": "update" if existing is not None else "create"}


def activate_reserve_pool(clue_id: str) -> dict:
    """
    计算后备池激活优先级排序。

    规则：后备池激活分 = 原综合分 × 0.9 + 时间衰减补偿（每 30 天 +0.1，上限 1.0）
    """
    import datetime
    cache = load_cache()

    clue = None
    for c in cache.get("product_clues", []):
        if c.get("clue_id") == clue_id:
            clue = c
            break

    if not clue:
        return {"error": f"未找到线索 {clue_id}"}

    now = datetime.datetime.now()
    activated = []

    for rec in clue.get("recommendations", []):
        if rec.get("status") != "后备池":
            continue

        original_score = rec.get("score", 5.0)
        rec_time_str = rec.get("recommended_at", "")
        try:
            rec_time = datetime.datetime.fromisoformat(rec_time_str)
            days_passed = (now - rec_time).days
            time_bonus = min(days_passed / 30 * 0.1, 1.0)
        except (ValueError, TypeError):
            time_bonus = 0.5  # 无法解析时间时取中间值

        activation_score = round(original_score * 0.9 + time_bonus, 2)

        activated.append({
            "company_name": rec.get("company_name", ""),
            "uscc": rec.get("uscc", ""),
            "original_score": original_score,
            "activation_score": activation_score,
            "days_since_original": days_passed,
        })

    activated.sort(key=lambda x: x["activation_score"], reverse=True)

    return {"activations": activated}


# === 主入口 ===

def main():
    if len(sys.argv) > 1:
        raw = sys.argv[1]
    else:
        raw = sys.stdin.read()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"JSON 解析失败: {str(e)}"}, ensure_ascii=False))
        sys.exit(1)

    mode = data.get("mode", "match")

    if mode == "match":
        result = match_clue(
            data.get("product_keywords", []),
            data.get("target_industry", ""),
        )
        print(json.dumps({"matched": result is not None, "clue": result}, ensure_ascii=False, indent=2))

    elif mode == "exclude":
        result = generate_exclude_lists(
            data.get("product_keywords", []),
            data.get("target_industry", ""),
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif mode == "add":
        result = add_recommendations(data.get("clue_data", {}))
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif mode == "activate":
        result = activate_reserve_pool(data.get("clue_id", ""))
        print(json.dumps(result, ensure_ascii=False, indent=2))

    else:
        print(json.dumps({"error": f"未知模式: {mode}，支持 match/exclude/add/activate"}, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
