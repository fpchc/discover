"""LLM 接入：提供方解析、流式客户端、语义分片解析。"""

from app.capabilities.llm.client import LLMClient
from app.capabilities.llm.models import ChatMessage, ChatRequest, ChatToolSpec
from app.capabilities.llm.providers import ProviderRegistry, resolve_api_key
from app.capabilities.llm.stream_parser import (
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
