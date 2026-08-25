"""推荐历史持久化（结构化状态入 PG，脚本纯计算）。

去重历史此前由脚本读写工作区文件；现入 dedup_clues 表。脚本变为无状态：
平台注入 history 文档、脚本返回结果，add 模式经结果 `_upsert` 由平台回写。
CLAUDE.md §3：持久化载体为 ORM；脚本侧按 JSON 契约传 dict。
"""

from __future__ import annotations

import contextlib
from datetime import datetime
from typing import cast

from sqlalchemy import select

from app.db.engine import Database
from app.db.models import DedupClue

_HISTORY_VERSION = "1.0"


def _as_str_list(value: object) -> list[str]:
    """脚本 JSON 里的任意值 → 字符串列表（非列表则空）。"""
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _as_dict_list(value: object) -> list[dict[str, object]]:
    """脚本 JSON 里的任意值 → 字典列表（非列表则空）。"""
    if not isinstance(value, list):
        return []
    return cast(list[dict[str, object]], value)


def _as_int(value: object) -> int:
    """脚本 JSON 里的任意值 → int（非数值则 0）。"""
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return 0


def _clue_to_dict(row: DedupClue) -> dict[str, object]:
    """ORM 线索 → 脚本约定的线索字典。"""
    return {
        "clue_id": row.clue_id,
        "product_keywords": row.product_keywords,
        "target_industry": row.target_industry,
        "created_at": row.created_at.isoformat() if row.created_at else "",
        "report_path": row.report_path,
        "recommendations": row.recommendations,
        "excluded_companies": row.excluded_companies,
        "total_found": row.total_found,
        "remaining_pool": row.remaining_pool,
    }


class HistoryStore:
    """推荐历史仓库：注入脚本的 history 文档、持久化 add 结果。"""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def load_history(self) -> dict[str, object]:
        """读取全部线索，组装脚本约定的 history 文档（空历史返回空 doc）。"""
        async with self._db.session_factory() as session:
            rows = (await session.scalars(select(DedupClue).order_by(DedupClue.created_at))).all()
        return {
            "version": _HISTORY_VERSION,
            "product_clues": [_clue_to_dict(row) for row in rows],
        }

    async def upsert_clue(self, clue: dict[str, object]) -> None:
        """按 clue_id 新增或更新线索（脚本 add 模式 _upsert 回写）。"""
        clue_id = str(clue.get("clue_id", ""))
        async with self._db.session_factory() as session:
            row = await session.get(DedupClue, clue_id)
            if row is None:
                row = DedupClue(clue_id=clue_id)
                session.add(row)
            row.product_keywords = _as_str_list(clue.get("product_keywords"))
            row.target_industry = str(clue.get("target_industry", ""))
            row.report_path = str(clue.get("report_path", ""))
            row.recommendations = _as_dict_list(clue.get("recommendations"))
            row.excluded_companies = _as_dict_list(clue.get("excluded_companies"))
            row.total_found = _as_int(clue.get("total_found"))
            row.remaining_pool = _as_int(clue.get("remaining_pool"))
            created = clue.get("created_at")
            if isinstance(created, str) and created:
                with contextlib.suppress(ValueError):
                    row.created_at = datetime.fromisoformat(created)
            await session.commit()
