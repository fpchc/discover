"""腾讯 WSA 搜索提供方适配器。

平台经标准 MCP（Streamable HTTP）连接本地 tencent_mcp 服务；本服务内部经 httpx 直连
腾讯 WSA SearchPro REST 端点。结果统一渲染为模型可读文本，按标题去重；调用失败抛
SearchServiceError（信息已脱敏）。
"""

from __future__ import annotations

import abc
import json
import logging
import re
import time
from types import TracebackType
from typing import Any, ClassVar

import httpx

from local_mcp.tencent_mcp.settings import TencentMCPSettings

logger = logging.getLogger(__name__)


def _clip(query: str, max_chars: int) -> str:
    """日志截断：超长查询截断到 max_chars 并加省略号。"""
    if len(query) <= max_chars:
        return query
    return query[:max_chars] + "…"


class SearchServiceError(Exception):
    """提供方调用失败（上游业务错误 / 连接失败），信息已脱敏。"""


def _dot_get(data: dict[str, object], path: str) -> object:
    """按点路径取值（如 "Response.Pages"）；任一级缺失返回 None。"""
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
    entries_are_json_strings: bool = False,
) -> str:
    """结果数组渲染为文本：标题 + 来源/日期 + 链接 + 摘要，按标题去重。"""
    lines: list[str] = []
    seen: set[str] = set()
    for raw in results:
        item: object = raw
        if entries_are_json_strings:
            if not isinstance(raw, str):
                continue
            try:
                item = json.loads(raw)
            except json.JSONDecodeError:
                continue
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
        settings: TencentMCPSettings,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._http = http_client

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

    async def _post_json(self, url: str, *, json_body: dict[str, object]) -> dict[str, object]:
        """POST JSON 并解析响应；网络/HTTP/JSON 异常统一转 SearchServiceError。"""
        http = self._require_http()
        try:
            response = await http.post(url, json=json_body)
        except httpx.RequestError as exc:
            raise SearchServiceError("搜索服务连接失败") from exc
        try:
            response.raise_for_status()
            payload: Any = response.json()
        except (httpx.HTTPStatusError, ValueError) as exc:
            raise SearchServiceError(f"搜索服务响应异常（HTTP {response.status_code}）") from exc
        if not isinstance(payload, dict):
            raise SearchServiceError("搜索服务响应不是合法 JSON")
        return payload


class TencentSearchProvider(SearchProvider):
    """腾讯 WSA 联网搜索（POST SearchPro，Bearer 鉴权，响应 Pages 为 JSON 字符串数组）。"""

    _ENTRY_FIELDS: ClassVar[dict[str, str]] = {
        "title": "title",
        "snippet": "passage",
        "url": "url",
        "date": "date",
        "site": "site",
    }

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._settings.wsa_api_key}"}

    async def search(self, query: str) -> str:
        if not self._settings.wsa_api_key:
            raise SearchServiceError("腾讯搜索未配置 WSA_API_KEY")
        started = time.monotonic()
        logger.info(
            "腾讯搜索开始",
            extra={
                "query": _clip(query, self._settings.log_query_max_chars),
                "query_len": len(query),
            },
        )
        try:
            payload = await self._post_json(
                self._settings.wsa_search_url, json_body={"Query": query}
            )
            err = _dot_get(payload, "Response.Error")
            if isinstance(err, dict):
                code = str(err.get("Code", ""))
                message = str(err.get("Message", ""))
                raise SearchServiceError(f"腾讯搜索上游错误：{code} {message}".strip())
            pages = _dot_get(payload, "Response.Pages")
            if not isinstance(pages, list):
                text = "未找到相关结果"
            else:
                text = (
                    render_entries(
                        pages, entry_fields=self._ENTRY_FIELDS, entries_are_json_strings=True
                    )
                    or "未找到相关结果"
                )
        except SearchServiceError as exc:
            logger.warning("腾讯搜索失败", extra={"query_len": len(query), "error": str(exc)})
            raise
        logger.info(
            "腾讯搜索完成",
            extra={
                "query_len": len(query),
                "duration_ms": int((time.monotonic() - started) * 1000),
                "result_len": len(text),
            },
        )
        return text
