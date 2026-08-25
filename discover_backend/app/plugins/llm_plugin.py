"""llm 插件：加载模型提供方注册表 + LLMClient + ProviderRegistry。

自原 container 迁出：LLMClient 随插件生命周期 __aenter__/__aexit__；
resolve_api_key 绑定 settings（真实环境变量优先，其次 .env 文件，不写入
os.environ）。
"""

from __future__ import annotations

from app.config.loader import LLMProvider, load_llm_providers
from app.config.settings import Settings
from app.llm.client import LLMClient
from app.llm.providers import ProviderRegistry, resolve_api_key
from app.plugins.base import Plugin, register


@register
class LLMPlugin(Plugin):
    """模型提供方注册表 + 流式客户端。"""

    name = "llm"

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self._client = LLMClient(settings)
        self._providers: ProviderRegistry | None = None

    @classmethod
    def is_enabled(cls, settings: Settings) -> bool:
        return settings.llm_enabled

    @property
    def client(self) -> LLMClient:
        return self._client

    @property
    def providers(self) -> ProviderRegistry:
        assert self._providers is not None
        return self._providers

    def resolve_api_key(self, provider: LLMProvider) -> str:
        """解析提供方密钥（绑定 settings：真实环境变量优先，其次 .env）。"""
        return resolve_api_key(provider, settings=self._settings)

    async def startup(self) -> None:
        await self._client.__aenter__()
        registry = await load_llm_providers(self._settings.llm_providers_path)
        self._providers = ProviderRegistry(registry)

    async def shutdown(self) -> None:
        await self._client.__aexit__(None, None, None)
