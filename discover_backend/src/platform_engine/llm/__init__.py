"""LLM 接入：提供方解析、流式客户端、语义分片解析。"""

from platform_engine.llm.client import LLMClient
from platform_engine.llm.models import ChatMessage, ChatRequest, ChatToolSpec
from platform_engine.llm.providers import ProviderRegistry, resolve_api_key
from platform_engine.llm.stream_parser import (
    FinishChunk,
    PhaseSwitchChunk,
    SemanticChunk,
    TextChunk,
    ThinkingChunk,
    ToolCall,
    ToolCallChunk,
    ToolCallsChunk,
    UsageChunk,
)

__all__ = [
    "ChatMessage",
    "ChatRequest",
    "ChatToolSpec",
    "FinishChunk",
    "LLMClient",
    "PhaseSwitchChunk",
    "ProviderRegistry",
    "SemanticChunk",
    "TextChunk",
    "ThinkingChunk",
    "ToolCall",
    "ToolCallChunk",
    "ToolCallsChunk",
    "UsageChunk",
    "resolve_api_key",
]
