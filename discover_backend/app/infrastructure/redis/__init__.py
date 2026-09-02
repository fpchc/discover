"""Redis 基础设施：客户端 + Cache/Lock 封装 + 生命周期访问器（认证会话层硬依赖）。"""

from app.infrastructure.redis.client import Cache, Lock, get_cache, get_client, get_lock

__all__ = ["Cache", "Lock", "get_cache", "get_client", "get_lock"]
