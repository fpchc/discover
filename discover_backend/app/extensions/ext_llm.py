"""LLM 扩展：加载模型提供方注册表 + LLMClient + ProviderRegistry。

startup 随生命周期进入 LLM 客户端并加载提供方 yaml；resolve_api_key 绑定
当前应用配置（真实环境变量优先，其次 .env 文件，不写入 os.environ）。
"""

from __future__ import annotations

from fastapi import FastAPI

from app.config.loader import LLMProvider, load_llm_providers
from app.extensions.base import active_settings
from app.llm.client import LLMClient
from app.llm.providers import ProviderRegistry
from app.llm.providers import resolve_api_key as _resolve_api_key

_client: LLMClient | None = None
_providers: ProviderRegistry | None = None


def is_enabled() -> bool:
    """由配置开关控制。"""
    return active_settings().llm_enabled


def init_app(app: FastAPI | None) -> None:
    """构造惰性 LLM 客户端（不建连）。"""
    global _client
    _client = LLMClient(active_settings())


async def startup(app: FastAPI) -> None:
    """进入客户端生命周期并加载提供方注册表。"""
    global _providers
    assert _client is not None
    await _client.__aenter__()
    registry = await load_llm_providers(active_settings().llm_providers_path)
    _providers = ProviderRegistry(registry)


async def shutdown(app: FastAPI) -> None:
    """退出客户端生命周期，释放连接。"""
    global _client
    if _client is not None:
        await _client.__aexit__(None, None, None)
        _client = None


def get_client() -> LLMClient:
    """取 LLM 流式客户端；扩展未启用时抛断言。"""
    assert _client is not None
    return _client


def get_providers() -> ProviderRegistry:
    """取提供方注册表。"""
    assert _providers is not None
    return _providers


def resolve_api_key(provider: LLMProvider) -> str:
    """解析提供方密钥（绑定当前应用配置）。"""
    return _resolve_api_key(provider, settings=active_settings())
