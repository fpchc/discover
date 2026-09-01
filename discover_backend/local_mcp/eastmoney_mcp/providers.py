"""东方财富（eastmoney）搜索提供方适配器：东财 JSONP 资讯搜索。

平台经标准 MCP（Streamable HTTP）连接本地 eastmoney_mcp 服务；本服务内部经 httpx 直连
东财 JSONP REST 端点。免费源按 IP 限流，做最小调用间隔节流。结果统一渲染为模型可读文本，
按标题去重；调用失败抛 SearchServiceError（信息已脱敏）。
"""

from __future__ import annotations

import abc
import json
import logging
import re
import time
from types import TracebackType
from typing import Any, ClassVar

import anyio
import httpx

from local_mcp.eastmoney_mcp.settings import EastmoneyMCPSettings

logger = logging.getLogger(__name__)


def _clip(query: str, max_chars: int) -> str:
    """日志截断：超长查询截断到 max_chars 并加省略号。"""
    if len(query) <= max_chars:
        return query
    return query[:max_chars] + "…"


class SearchServiceError(Exception):
    """提供方调用失败（上游业务错误 / 连接失败），信息已脱敏。"""


def _dot_get(data: dict[str, object], path: str) -> object:
    """按点路径取值（如 "result.cmsArticleWebOld"）；任一级缺失返回 None。"""
    current: object = data
    for key in path.split("."):
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def _field(item: dict[str, object], name: str | None) -> str:
    """取条目字段并清理 HTML 标签；缺失返回空串。"""
    if not name:
        return ""
    value = item.get(name)
    if value is None:
        return ""
    return re.sub(r"<[^>]+>", "", str(value)).strip()


def render_entries(
    results: list[object],
    *,
    entry_fields: dict[str, str],
) -> str:
    """结果数组渲染为文本：标题 + 来源/日期 + 链接 + 摘要，按标题去重。"""
    lines: list[str] = []
    seen: set[str] = set()
    for raw in results:
        item: object = raw
        if not isinstance(item, dict):
            continue
        title = _field(item, entry_fields.get("title"))
        if not title or title in seen:
            continue
        seen.add(title)
        parts = [f"- {title}"]
        site = _field(item, entry_fields.get("site"))
        date = _field(item, entry_fields.get("date"))
        meta = "  ·  ".join(part for part in (site, date) if part)
        if meta:
            parts.append(f"  {meta}")
        url = _field(item, entry_fields.get("url"))
        if url:
            parts.append(f"  {url}")
        snippet = _field(item, entry_fields.get("snippet"))
        if snippet:
            parts.append(f"  {snippet}")
        lines.append("\n".join(parts))
    return "\n\n".join(lines)


class SearchProvider(abc.ABC):
    """搜索提供方基类：类式异步生命周期；httpx 客户端可注入（测试用 MockTransport）。"""

    def __init__(
        self,
        settings: EastmoneyMCPSettings,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._http = http_client
        self._throttle_lock = anyio.Lock()
        self._last_call = 0.0

    async def __aenter__(self) -> SearchProvider:
        if self._http is None:
            self._http = httpx.AsyncClient(
                timeout=httpx.Timeout(self._settings.http_timeout_seconds),
                headers=self._headers(),
            )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    @abc.abstractmethod
    def _headers(self) -> dict[str, str]:
        """出站请求附加头（鉴权 / 来源）。"""

    @abc.abstractmethod
    async def search(self, query: str) -> str:
        """按关键词搜索，返回渲染后文本；调用失败抛 SearchServiceError。"""

    def _require_http(self) -> httpx.AsyncClient:
        if self._http is None:
            raise RuntimeError("SearchProvider 尚未进入生命周期")
        return self._http

    async def _throttle(self, interval: float) -> None:
        """按 IP 限流的免费源最小调用间隔。"""
        if interval <= 0:
            return
        async with self._throttle_lock:
            now = time.monotonic()
            wait = interval - (now - self._last_call)
            if wait > 0:
                await anyio.sleep(wait)
            self._last_call = time.monotonic()

    async def _get_text(self, url: str, *, params: dict[str, str]) -> str:
        """GET 查询并返回原始文本；网络/HTTP 异常统一转 SearchServiceError。"""
        http = self._require_http()
        try:
            response = await http.get(url, params=params)
        except httpx.RequestError as exc:
            raise SearchServiceError("搜索服务连接失败") from exc
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise SearchServiceError(f"搜索服务响应异常（HTTP {response.status_code}）") from exc
        return response.text


class EastmoneySearchProvider(SearchProvider):
    """东方财富资讯搜索（GET JSONP，免鉴权，关键词经 param 模板注入）。"""

    _PARAM_TEMPLATE = (
        '{"uid":"","keyword":"{query}","type":["cmsArticleWebOld"],"client":"web",'
        '"clientVersion":"curr","param":{"cmsArticleWebOld":{"searchScope":"default",'
        '"sort":"default","pageIndex":1,"pageSize":10,"preTag":"","postTag":""}}}'
    )
    _CALLBACK = "jQuery_news"
    _ENTRY_FIELDS: ClassVar[dict[str, str]] = {
        "title": "title",
        "snippet": "content",
        "url": "url",
        "date": "date",
        "site": "mediaName",
    }

    def _headers(self) -> dict[str, str]:
        return {
            "Referer": "https://so.eastmoney.com/",
            "User-Agent": "Mozilla/5.0",
        }

    async def search(self, query: str) -> str:
        await self._throttle(self._settings.eastmoney_min_interval_seconds)
        started = time.monotonic()
        logger.info(
            "东财搜索开始",
            extra={
                "query": _clip(query, self._settings.log_query_max_chars),
                "query_len": len(query),
            },
        )
        try:
            escaped = json.dumps(query, ensure_ascii=False)
            param = self._PARAM_TEMPLATE.replace("{query}", escaped[1:-1])
            text = await self._get_text(
                self._settings.eastmoney_search_url,
                params={"cb": self._CALLBACK, "param": param},
            )
            payload = self._unwrap_jsonp(text)
            results = _dot_get(payload, "result.cmsArticleWebOld")
            if not isinstance(results, list):
                text = "未找到相关结果"
            else:
                text = render_entries(results, entry_fields=self._ENTRY_FIELDS) or "未找到相关结果"
        except SearchServiceError as exc:
            logger.warning("东财搜索失败", extra={"query_len": len(query), "error": str(exc)})
            raise
        logger.info(
            "东财搜索完成",
            extra={
                "query_len": len(query),
                "duration_ms": int((time.monotonic() - started) * 1000),
                "result_len": len(text),
            },
        )
        return text

    @staticmethod
    def _unwrap_jsonp(text: str) -> dict[str, object]:
        """剥掉 JSONP 外壳 `cb({...})` 再解析。"""
        start = text.find("(")
        end = text.rfind(")")
        if start != -1 and end != -1 and end > start:
            text = text[start + 1 : end]
        try:
            payload: Any = json.loads(text)
        except json.JSONDecodeError as exc:
            raise SearchServiceError("东方财富响应不是合法 JSON") from exc
        if not isinstance(payload, dict):
            raise SearchServiceError("东方财富响应不是合法 JSON")
        return payload
