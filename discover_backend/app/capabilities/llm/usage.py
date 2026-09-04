"""回合级 token 用量聚合（含 prompt 缓存命中/写入）。

防腐层下游：StreamParser 把提供方私有用量字段统一为平台标准的 UsageChunk，
Runner 每回合持一个 UsageAggregator，各 LLM 调用点只调 add()，收尾调
snapshot()，内部不写任何累加逻辑（SRP，评审采纳）。
"""

from __future__ import annotations

from app.capabilities.llm.stream_parser import UsageChunk

# UsageChunk 字段 → LLMUsageUpdated.usage 字典键
_FIELD_ALIASES: tuple[tuple[str, str], ...] = (
    ("input_tokens", "input"),
    ("output_tokens", "output"),
    ("total_tokens", "total"),
    ("cached_read_tokens", "cached_read"),
    ("cached_write_tokens", "cached_write"),
)


class UsageAggregator:
    """回合级 usage 累加器：add 归集分片，snapshot 输出聚合 dict。"""

    def __init__(self) -> None:
        self._totals: dict[str, int] = {alias: 0 for _, alias in _FIELD_ALIASES}

    def add(self, chunk: UsageChunk) -> None:
        for field, alias in _FIELD_ALIASES:
            self._totals[alias] += getattr(chunk, field)

    def snapshot(self) -> dict[str, int]:
        """回合聚合结果（input/output/total/cached_read/cached_write）。"""
        return dict(self._totals)
