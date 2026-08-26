#!/usr/bin/env python3
"""EITIA 推荐历史去重脚本（P1，无状态纯计算）。

契约：stdin 一次写入 UTF-8 JSON，stdout 输出 UTF-8 JSON，非 0 退出码表示失败。
去重历史由平台经 stdin 的 `history` 字段注入（持久化在平台侧 dedup_clues 表），
本脚本不做文件读写、不读环境变量路径。

模式：match / exclude / add / activate。
- match / exclude / activate：对注入的 history 纯计算后直接输出结果。
- add：计算新线索并经结果 `_upsert` 字段返回，平台据此持久化回写历史。

用法：
  echo '{"history":{"version":"1.0","product_clues":[]},"mode":"exclude","product_keywords":["高速背板连接器"],"target_industry":"数据中心交换机"}' | python dedup_manager.py
"""

from __future__ import annotations

import datetime
import json
import sys
from typing import Any

SIMILARITY_THRESHOLD: float = 0.7
KEYWORD_WEIGHT: float = 0.6
INDUSTRY_WEIGHT: float = 0.4


def default_cache() -> dict[str, Any]:
    return {"version": "1.0", "product_clues": []}


def normalize_keywords(keywords: list[str]) -> set[str]:
    return {k.strip().lower() for k in keywords if k.strip()}


def jaccard_similarity(set_a: set[str], set_b: set[str]) -> float:
    if not set_a or not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union > 0 else 0.0


def _similarity(
    input_keywords: set[str], input_industry: str, clue: dict[str, Any]
) -> float:
    clue_keywords = normalize_keywords(clue.get("product_keywords", []))
    clue_industry = str(clue.get("target_industry", "")).strip().lower()
    kw_sim = jaccard_similarity(input_keywords, clue_keywords)
    if not input_industry or not clue_industry:
        ind_sim = 0.5
    elif input_industry == clue_industry:
        ind_sim = 1.0
    elif input_industry in clue_industry or clue_industry in input_industry:
        ind_sim = 0.8
    else:
        ind_sim = 0.0
    return kw_sim * KEYWORD_WEIGHT + ind_sim * INDUSTRY_WEIGHT


def match_clue(
    cache: dict[str, Any], product_keywords: list[str], target_industry: str = ""
) -> dict[str, Any] | None:
    """返回最相似的历史线索（≥ 阈值），否则 None。纯计算，history 由调用方注入。"""
    input_keywords = normalize_keywords(product_keywords)
    input_industry = target_industry.strip().lower()
    best: dict[str, Any] | None = None
    best_sim = 0.0
    for clue in cache.get("product_clues", []):
        if not isinstance(clue, dict):
            continue
        sim = _similarity(input_keywords, input_industry, clue)
        if sim >= SIMILARITY_THRESHOLD and sim > best_sim:
            best_sim = sim
            best = clue
    if best is not None:
        best["_similarity"] = best_sim
    return best


def generate_exclude_lists(
    cache: dict[str, Any], product_keywords: list[str], target_industry: str = ""
) -> dict[str, Any]:
    """生成排除列表（已推荐 + 后备池 + 手动排除）。"""
    matched = match_clue(cache, product_keywords, target_industry)
    if matched is None:
        return {
            "matched": False,
            "similarity": 0.0,
            "recommended": [],
            "reserve_pool": [],
            "all_excluded": [],
            "matched_clue": None,
        }
    recommended: list[dict[str, Any]] = []
    reserve_pool: list[dict[str, Any]] = []
    all_excluded: list[dict[str, Any]] = []
    for rec in matched.get("recommendations", []):
        if not isinstance(rec, dict):
            continue
        entry = {
            "company_name": rec.get("company_name", ""),
            "uscc": rec.get("uscc", ""),
            "status": rec.get("status", ""),
        }
        if entry["status"] == "已推荐":
            recommended.append(entry)
        elif entry["status"] == "后备池":
            reserve_pool.append(entry)
        all_excluded.append(entry)
    for name in matched.get("excluded_companies", []):
        all_excluded.append({"company_name": name, "uscc": "", "status": "手动排除"})
    return {
        "matched": True,
        "similarity": float(matched.pop("_similarity", 0.0)),
        "matched_clue": {
            "clue_id": matched.get("clue_id", ""),
            "created_at": matched.get("created_at", ""),
            "total_found": matched.get("total_found", 0),
            "remaining_pool": matched.get("remaining_pool", 0),
        },
        "recommended": recommended,
        "reserve_pool": reserve_pool,
        "all_excluded": all_excluded,
    }


def add_recommendations(clue_data: dict[str, Any]) -> dict[str, Any]:
    """计算新增/更新线索；不落盘，经 `_upsert` 交平台持久化（按 clue_id upsert）。"""
    today = datetime.date.today().strftime("%Y%m%d")
    product_key = "_".join(clue_data.get("product_keywords", ["unknown"])[:2])
    clue_id = f"{product_key}_{today}"
    recommendations = clue_data.get("recommendations", [])
    new_clue: dict[str, Any] = {
        "clue_id": clue_id,
        "product_keywords": clue_data.get("product_keywords", []),
        "target_industry": clue_data.get("target_industry", ""),
        "created_at": datetime.datetime.now().isoformat(),
        "report_path": clue_data.get("report_path", ""),
        "recommendations": recommendations,
        "excluded_companies": clue_data.get("excluded_companies", []),
        "total_found": sum(1 for r in recommendations if r.get("status") == "已推荐"),
        "remaining_pool": sum(1 for r in recommendations if r.get("status") == "后备池"),
    }
    return {
        "success": True,
        "clue_id": clue_id,
        "_upsert": new_clue,
    }


def activate_reserve_pool(cache: dict[str, Any], clue_id: str) -> dict[str, Any]:
    """后备池激活排序：原分 × 0.9 + 时间衰减补偿（每 30 天 +0.1，上限 1.0）。"""
    clue = next(
        (c for c in cache.get("product_clues", []) if isinstance(c, dict) and c.get("clue_id") == clue_id),
        None,
    )
    if clue is None:
        return {"error": f"未找到线索 {clue_id}"}
    now = datetime.datetime.now()
    activated: list[dict[str, Any]] = []
    for rec in clue.get("recommendations", []):
        if not isinstance(rec, dict) or rec.get("status") != "后备池":
            continue
        original_score = float(rec.get("score", 5.0))
        rec_time_str = rec.get("recommended_at", "")
        try:
            rec_time = datetime.datetime.fromisoformat(rec_time_str)
            days_passed = (now - rec_time).days
            time_bonus = min(days_passed / 30 * 0.1, 1.0)
        except (ValueError, TypeError):
            days_passed = 0
            time_bonus = 0.5
        activated.append(
            {
                "company_name": rec.get("company_name", ""),
                "uscc": rec.get("uscc", ""),
                "original_score": original_score,
                "activation_score": round(original_score * 0.9 + time_bonus, 2),
                "days_since_original": days_passed,
            }
        )
    activated.sort(key=lambda x: float(x["activation_score"]), reverse=True)
    return {"activations": activated}


def _emit_error(message: str) -> None:
    print(json.dumps({"error": message}, ensure_ascii=False))
    sys.exit(1)


def main() -> None:
    raw = sys.argv[1] if len(sys.argv) > 1 else sys.stdin.read()
    try:
        data: dict[str, Any] = json.loads(raw)
    except json.JSONDecodeError as exc:
        _emit_error(f"JSON 解析失败: {exc}")
    cache = data.get("history")
    if not isinstance(cache, dict):
        cache = default_cache()
    mode = data.get("mode", "match")
    if mode == "match":
        clue = match_clue(cache, data.get("product_keywords", []), data.get("target_industry", ""))
        print(json.dumps({"matched": clue is not None, "clue": clue}, ensure_ascii=False, indent=2))
    elif mode == "exclude":
        print(
            json.dumps(
                generate_exclude_lists(cache, data.get("product_keywords", []), data.get("target_industry", "")),
                ensure_ascii=False,
                indent=2,
            )
        )
    elif mode == "add":
        print(json.dumps(add_recommendations(data.get("clue_data", {})), ensure_ascii=False, indent=2))
    elif mode == "activate":
        print(json.dumps(activate_reserve_pool(cache, data.get("clue_id", "")), ensure_ascii=False, indent=2))
    else:
        _emit_error(f"未知模式: {mode}，支持 match/exclude/add/activate")


if __name__ == "__main__":
    main()
