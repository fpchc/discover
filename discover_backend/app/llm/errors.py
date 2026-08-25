"""LLM 错误分类：传输层异常 → 领域异常。

客户端只标记可重试性，不自行重试（llm-provider-spec §8）。分类：
连接失败 / 超时 → 可重试；鉴权 / 请求非法 / 内容过滤 → 不可重试。
错误信息不含密钥、不含完整请求体。
"""

import httpx

from app.errors.base import LLMConnectionError, LLMError, LLMTimeoutError


def classify_stream_error(exc: httpx.RequestError) -> LLMError:
    """把 httpx 传输异常映射为 LLM 领域异常（不含敏感细节）。"""
    if isinstance(exc, httpx.ConnectTimeout):
        return LLMConnectionError("连接模型服务超时")
    if isinstance(exc, httpx.TimeoutException):
        return LLMTimeoutError("请求超时（连接/读取/池）")
    if isinstance(exc, httpx.ConnectError):
        return LLMConnectionError("连接模型服务失败")
    return LLMConnectionError("模型服务传输错误")
