"""OpenAI 兼容协议流式客户端（httpx 直连，禁用 SDK）。

进程级复用：随应用生命周期创建，不每次请求新建（丢连接池会显著增加延迟）。
连接 / 分片间隔 / 总时长三套超时独立配置。错误只分类不重试。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import TracebackType

import anyio
import httpx

from app.capabilities.llm.errors import classify_stream_error
from app.capabilities.llm.models import ChatRequest
from app.capabilities.llm.stream_parser import SemanticChunk, StreamParser
from app.config.loader import LLMProvider
from app.config.settings import Settings
from app.shared.errors.base import (
    LLMAuthError,
    LLMBadRequestError,
    LLMRateLimitError,
    LLMServerError,
    LLMTimeoutError,
)
from app.shared.utils.sanitize import redact_sensitive, truncate


class LLMClient:
    """LLM 流式客户端。进程级复用，类式异步上下文管理器生命周期。"""

    def __init__(
        self,
        settings: Settings,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._http = http_client

    async def __aenter__(self) -> LLMClient:
        if self._http is None:
            self._http = self._build_http_client()
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

    def _build_http_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=self._settings.llm_connect_timeout_seconds,
                read=self._settings.llm_read_timeout_seconds,
                write=self._settings.llm_connect_timeout_seconds,
                pool=self._settings.llm_connect_timeout_seconds,
            )
        )

    def _require_http(self) -> httpx.AsyncClient:
        if self._http is None:
            raise RuntimeError("LLMClient 尚未进入生命周期（__aenter__）")
        return self._http

    async def stream_chat(
        self,
        *,
        provider: LLMProvider,
        api_key: str,
        request: ChatRequest,
    ) -> AsyncIterator[SemanticChunk]:
        """发起流式调用，产出语义分类分片。传输异常映射为领域异常抛出。"""
        http = self._require_http()
        url = provider.base_url.rstrip("/") + "/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}"}
        payload = self._build_payload(provider, request)
        parser = StreamParser(thinking_field=provider.thinking_field)
        try:
            with anyio.fail_after(self._settings.llm_total_timeout_seconds):
                async with http.stream("POST", url, json=payload, headers=headers) as response:
                    await self._raise_for_status(response)
                    async for line in response.aiter_lines():
                        data = self._extract_data(line)
                        if data == "[DONE]":
                            break
                        if data is not None:
                            for chunk in parser.feed(data):
                                yield chunk
        except httpx.RequestError as exc:
            raise classify_stream_error(exc) from exc
        except TimeoutError as exc:
            raise LLMTimeoutError("总时长超限，已中断流式调用") from exc

    def _build_payload(self, provider: LLMProvider, request: ChatRequest) -> dict[str, object]:
        payload: dict[str, object] = {
            "model": provider.model,
            "messages": [message.model_dump(exclude_none=True) for message in request.messages],
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if request.tools:
            payload["tools"] = [tool.model_dump(exclude_none=True) for tool in request.tools]
        if request.thinking and provider.supports_thinking:
            payload["enable_thinking"] = True
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        return payload

    async def _raise_for_status(self, response: httpx.Response) -> None:
        if response.status_code < 400:
            return
        detail = await self._error_detail(response)
        if response.status_code in (401, 403):
            raise LLMAuthError(f"鉴权失败（HTTP {response.status_code}）：{detail}")
        if response.status_code == 429:
            raise LLMRateLimitError(f"限流（HTTP 429）：{detail}")
        if response.status_code == 400:
            raise LLMBadRequestError(f"请求非法（HTTP 400）：{detail}")
        raise LLMServerError(f"服务端错误（HTTP {response.status_code}）：{detail}")

    async def _error_detail(self, response: httpx.Response) -> str:
        try:
            body = (await response.aread()).decode("utf-8", errors="replace")
        except (httpx.RequestError, httpx.DecodingError):
            return ""
        return truncate(
            redact_sensitive(body),
            max_length=self._settings.error_message_max_chars,
        )

    @staticmethod
    def _extract_data(line: str) -> str | None:
        stripped = line.strip()
        if not stripped.startswith("data:"):
            return None
        return stripped[len("data:") :].strip()
