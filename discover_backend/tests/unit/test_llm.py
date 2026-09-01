"""Step 4 LLM 客户端测试。"""

import json

import httpx
import pytest
from app.config.loader import LLMProvider, LLMRegistry
from app.config.settings import Settings
from app.errors.base import (
    ConfigError,
    LLMAuthError,
    LLMConnectionError,
    LLMTimeoutError,
)
from app.llm.client import LLMClient
from app.llm.errors import classify_stream_error
from app.llm.models import ChatMessage, ChatRequest, ChatToolSpec, ToolFunction
from app.llm.providers import ProviderRegistry
from app.llm.stream_parser import (
    PhaseSwitchChunk,
    SemanticChunk,
    StreamParser,
    TextChunk,
    ThinkingChunk,
    ToolCallChunk,
    ToolCallsChunk,
    UsageChunk,
)
from app.llm.usage import UsageAggregator


def _provider() -> LLMProvider:
    return LLMProvider(
        id="qwen-max",
        display_name="Qwen",
        base_url="https://llm.example.com/v1",
        api_key_env="LLM_API_KEY",
        model="qwen-max",
        supports_thinking=True,
        thinking_field="reasoning_content",
        context_window=131072,
    )


def _mock_client(settings: Settings, handler: httpx.MockTransport) -> LLMClient:
    return LLMClient(settings, http_client=httpx.AsyncClient(transport=handler))


def test_stream_parser_classifies() -> None:
    parser = StreamParser(thinking_field="reasoning_content")
    chunks = parser.feed('{"choices": [{"delta": {"reasoning_content": "思考", "content": ""}}]}')
    assert chunks[0] == PhaseSwitchChunk(to="thinking")
    assert any(isinstance(chunk, ThinkingChunk) and chunk.text == "思考" for chunk in chunks)


def test_stream_parser_text_and_phase() -> None:
    parser = StreamParser(thinking_field="reasoning_content")
    chunks = parser.feed('{"choices": [{"delta": {"content": "你好"}}]}')
    assert chunks[0] == PhaseSwitchChunk(to="text")
    assert chunks[1] == TextChunk(text="你好")


def test_parser_strips_think_tags_from_content() -> None:
    parser = StreamParser(thinking_field="reasoning_content")
    chunks = parser.feed(
        '{"choices": [{"delta": {"content": "</think>东莞市钿威电子科技有限公司"}}]}'
    )
    text = "".join(c.text for c in chunks if isinstance(c, TextChunk))
    assert text == "东莞市钿威电子科技有限公司"
    assert "</think>" not in text


def test_parser_strips_think_tags_from_reasoning() -> None:
    parser = StreamParser(thinking_field="reasoning_content")
    payload = (
        '{"choices": [{"delta": {"reasoning_content": "<think>先分析证据</think>",'
        ' "content": ""}}]}'
    )
    chunks = parser.feed(payload)
    thinking = "".join(c.text for c in chunks if isinstance(c, ThinkingChunk))
    assert thinking == "先分析证据"
    assert "<think>" not in thinking
    assert "</think>" not in thinking


def test_parser_does_not_complete_tool_call_early() -> None:
    parser = StreamParser(thinking_field="reasoning_content")
    first = parser.feed(
        '{"choices": [{"delta": {"tool_calls": [{"index": 0,'
        ' "function": {"name": "f", "arguments": "{}"}}]}}]}'
    )
    assert not any(isinstance(chunk, ToolCallsChunk) for chunk in first)
    second = parser.feed(
        '{"choices": [{"delta": {"tool_calls": [{"index": 0,'
        ' "function": {"arguments": "{\\"a\\":1}"}}]}}]}'
    )
    assert not any(isinstance(chunk, ToolCallsChunk) for chunk in second)
    final = parser.feed('{"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}')
    calls = [chunk for chunk in final if isinstance(chunk, ToolCallsChunk)]
    assert calls[0].tool_calls[0].name == "f"
    assert calls[0].tool_calls[0].arguments == '{}{"a":1}'


def test_parser_usage_chunk() -> None:
    parser = StreamParser(thinking_field="reasoning_content")
    chunks = parser.feed(
        '{"usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}'
    )
    usage = next(chunk for chunk in chunks if isinstance(chunk, UsageChunk))
    assert usage.total_tokens == 15
    assert usage.input_tokens == 10
    assert usage.cached_read_tokens == 0
    assert usage.cached_write_tokens == 0


def test_parser_usage_cached_tokens_openai_style() -> None:
    parser = StreamParser(thinking_field="reasoning_content")
    chunks = parser.feed(
        '{"usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120,'
        ' "prompt_tokens_details": {"cached_tokens": 80}}}'
    )
    usage = next(chunk for chunk in chunks if isinstance(chunk, UsageChunk))
    assert usage.input_tokens == 100
    assert usage.cached_read_tokens == 80
    assert usage.cached_write_tokens == 0


def test_parser_usage_cached_tokens_deepseek_style() -> None:
    parser = StreamParser(thinking_field="reasoning_content")
    chunks = parser.feed(
        '{"usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120,'
        ' "prompt_cache_hit_tokens": 60, "prompt_cache_miss_tokens": 40}}'
    )
    usage = next(chunk for chunk in chunks if isinstance(chunk, UsageChunk))
    assert usage.cached_read_tokens == 60
    assert usage.cached_write_tokens == 0


def test_parser_usage_cached_tokens_anthropic_style() -> None:
    parser = StreamParser(thinking_field="reasoning_content")
    chunks = parser.feed(
        '{"usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120,'
        ' "cache_read_input_tokens": 70, "cache_creation_input_tokens": 30}}'
    )
    usage = next(chunk for chunk in chunks if isinstance(chunk, UsageChunk))
    assert usage.cached_read_tokens == 70
    assert usage.cached_write_tokens == 30


def test_usage_aggregator_add_and_snapshot() -> None:
    aggregator = UsageAggregator()
    aggregator.add(
        UsageChunk(input_tokens=100, output_tokens=20, total_tokens=120, cached_read_tokens=80)
    )
    aggregator.add(UsageChunk(input_tokens=50, output_tokens=10, total_tokens=60))
    assert aggregator.snapshot() == {
        "input": 150,
        "output": 30,
        "total": 180,
        "cached_read": 80,
        "cached_write": 0,
    }


def test_usage_aggregator_empty_snapshot() -> None:
    assert UsageAggregator().snapshot() == {
        "input": 0,
        "output": 0,
        "total": 0,
        "cached_read": 0,
        "cached_write": 0,
    }


def test_provider_registry_resolve_and_alias() -> None:
    registry = LLMRegistry(
        aliases={"opus": "qwen-max"},
        providers=[_provider()],
    )
    resolver = ProviderRegistry(registry)
    assert resolver.resolve("opus").id == "qwen-max"
    assert resolver.resolve("qwen-max").model == "qwen-max"
    with pytest.raises(ConfigError):
        resolver.resolve("unknown-provider")


async def test_client_stream_classifies_and_assembles() -> None:
    lines = [
        'data: {"choices": [{"delta": {"reasoning_content": "先分析", "content": ""}}]}',
        'data: {"choices": [{"delta": {"content": "答案"}}]}',
        (
            'data: {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "t1",'
            ' "function": {"name": "search", "arguments": "{\\"q\\":"}}]}}]}'
        ),
        (
            'data: {"choices": [{"delta": {"tool_calls": [{"index": 0,'
            ' "function": {"arguments": "\\"测试\\"}"}}]}}]}'
        ),
        'data: {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}',
        ('data: {"usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}'),
        "data: [DONE]",
    ]
    body = "\n".join(lines)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=body)

    settings = Settings(_env_file=None)
    client = _mock_client(settings, httpx.MockTransport(handler))
    request = ChatRequest(
        messages=[ChatMessage(role="user", content="你好")],
        tools=[ChatToolSpec(function=ToolFunction(name="search", parameters={}))],
        thinking=True,
    )
    chunks: list[SemanticChunk] = [
        chunk
        async for chunk in client.stream_chat(provider=_provider(), api_key="k", request=request)
    ]
    assert any(isinstance(chunk, ThinkingChunk) for chunk in chunks)
    assert any(isinstance(chunk, TextChunk) for chunk in chunks)
    assert any(isinstance(chunk, ToolCallChunk) for chunk in chunks)
    calls = next(chunk for chunk in chunks if isinstance(chunk, ToolCallsChunk))
    assert calls.tool_calls[0].id == "t1"
    assert calls.tool_calls[0].name == "search"
    assert calls.tool_calls[0].arguments == '{"q":"测试"}'
    usage = next(chunk for chunk in chunks if isinstance(chunk, UsageChunk))
    assert usage.total_tokens == 15


async def test_client_sends_enable_thinking() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, text="data: [DONE]\n\n")

    settings = Settings(_env_file=None)
    client = _mock_client(settings, httpx.MockTransport(handler))
    request = ChatRequest(messages=[ChatMessage(role="user", content="hi")], thinking=True)
    async for _ in client.stream_chat(provider=_provider(), api_key="k", request=request):
        pass
    body = captured["body"]
    assert isinstance(body, dict)
    assert body.get("enable_thinking") is True
    assert body.get("model") == "qwen-max"


async def test_client_auth_error_classified() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text='{"error": {"message": "invalid api key"}}')

    settings = Settings(_env_file=None)
    client = _mock_client(settings, httpx.MockTransport(handler))
    request = ChatRequest(messages=[ChatMessage(role="user", content="hi")])
    with pytest.raises(LLMAuthError):
        async for _ in client.stream_chat(provider=_provider(), api_key="k", request=request):
            pass


def test_classify_timeout_error() -> None:
    exc = httpx.ReadTimeout(
        "read timeout", request=httpx.Request("POST", "https://llm.example.com/v1/chat/completions")
    )
    error = classify_stream_error(exc)
    assert isinstance(error, LLMTimeoutError)
    assert error.retryable is True


def test_classify_connection_error() -> None:
    exc = httpx.ConnectError(
        "conn refused", request=httpx.Request("POST", "https://llm.example.com/v1/chat/completions")
    )
    error = classify_stream_error(exc)
    assert isinstance(error, LLMConnectionError)
    assert error.retryable is True
