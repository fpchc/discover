"""扩展配置访问：进程内"当前应用配置"间接层。

扩展统一经 active_settings() 读配置（保持 Dify 式无参钩子签名），由
initialize_extensions 在加载前 set_active_settings 注入；未注入时回落
get_settings() 单例。独立于 __init__.py，避免扩展模块 import 包时循环。
"""

from __future__ import annotations

from app.config.settings import Settings, get_settings

_ACTIVE_SETTINGS: Settings | None = None


def active_settings() -> Settings:
    """当前应用配置；未注入时回落进程级单例。"""
    return _ACTIVE_SETTINGS if _ACTIVE_SETTINGS is not None else get_settings()


def set_active_settings(settings: Settings) -> None:
    """注入应用配置（create_app 时调用）。"""
    global _ACTIVE_SETTINGS
    _ACTIVE_SETTINGS = settings
