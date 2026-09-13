"""模型提供方解析与密钥读取。

注册表数据模型与加载见 config.loader；本模块提供按标识解析（含智能体
偏好别名解引用）与密钥解析（经 Settings.resolve_secret，不写入 os.environ）。
"""

from app.config.loader import LLMProvider, LLMRegistry
from app.config.settings import Settings
from app.shared.errors.base import ConfigError


class ProviderRegistry:
    """提供方解析器。未找到的标识抛 ConfigError。"""

    def __init__(self, registry: LLMRegistry) -> None:
        self._registry = registry
        self._by_id: dict[str, LLMProvider] = {
            provider.id: provider for provider in registry.providers
        }

    def resolve(self, provider_id: str) -> LLMProvider:
        """按标识解析提供方；命中别名则解引用（如 opus → qwen3.7-max）。"""
        actual = self._registry.aliases.get(provider_id, provider_id)
        provider = self._by_id.get(actual)
        if provider is None:
            raise ConfigError(f"未注册的模型提供方标识：{provider_id}")
        return provider


def resolve_api_key(provider: LLMProvider, *, settings: Settings) -> str:
    """解析提供方密钥：真实环境变量优先，其次 .env 文件。缺失抛 ConfigError。"""
    value = settings.resolve_secret(provider.api_key_env)
    if not value:
        raise ConfigError(f"缺少密钥环境变量：{provider.api_key_env}")
    return value
