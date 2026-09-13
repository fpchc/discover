"""L —— 模型接入层（LLM）：请求/分片词汇 + 提供方协议适配。

核心边界之一（`LLM + Harness + Environment = Agent System`）。本包只描述
「怎么与模型对话」：请求模型、流式语义单元、提供方注册与密钥解析、httpx
流式客户端、传输异常分类、回合用量聚合。词汇（models/chunks）与适配
（client/providers/stream_parser/errors/usage/accessors）同属本支柱，不再
按 DDD 层拆开。

边界约束：本层不依赖 `harness` / `environment`，也不依赖 DDD 侧任何模块；
下游只有 `shared` / `config`（由 `tests/unit/test_layering.py` 守卫）。
"""

from app.llm.accessors import get_client, get_providers, resolve_api_key
from app.llm.chunks import (
    FinishChunk,
    PhaseSwitchChunk,
    SemanticChunk,
    SemanticChunkUnion,
    TextChunk,
    ThinkingChunk,
    ToolCall,
    ToolCallChunk,
    ToolCallsChunk,
    UsageChunk,
    semantic_adapter,
)
from app.llm.client import LLMClient
from app.llm.errors import classify_stream_error
from app.llm.models import (
    ChatMessage,
    ChatRequest,
    ChatToolCall,
    ChatToolCallFunction,
    ChatToolSpec,
    ToolFunction,
)
from app.llm.providers import ProviderRegistry

__all__ = [
    "ChatMessage",
    "ChatRequest",
    "ChatToolCall",
    "ChatToolCallFunction",
    "ChatToolSpec",
    "FinishChunk",
    "LLMClient",
    "PhaseSwitchChunk",
    "ProviderRegistry",
    "SemanticChunk",
    "SemanticChunkUnion",
    "TextChunk",
    "ThinkingChunk",
    "ToolCall",
    "ToolCallChunk",
    "ToolCallsChunk",
    "ToolFunction",
    "UsageChunk",
    "classify_stream_error",
    "get_client",
    "get_providers",
    "resolve_api_key",
    "semantic_adapter",
]
