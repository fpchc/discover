"""平台全局配置。

所有路径 / 阈值 / 超时 / 开关 / 模型标识一律在此定义，代码中不得出现硬编码字面量。
配置来源优先级：环境变量 > .env 文件 > 此处默认值。
密钥（未声明字段）经 resolve_secret 解析：真实环境变量 > .env 文件，不写入 os.environ。
"""

import os
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Final, Literal
from urllib.parse import quote_plus

from dotenv import dotenv_values
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic_settings.sources import ENV_FILE_SENTINEL, DotenvType

# 默认日志时区（IANA 名称）。
DEFAULT_LOG_TZ: Final[str] = "Asia/Shanghai"


class SideEffectType(StrEnum):
    """脚本 / 工具的副作用类型（工具描述符元数据）。"""

    READ_ONLY = "read_only"
    WRITE_FILE = "write_file"
    NETWORK = "network"
    PUBLISH = "publish"
    DELETE = "delete"


class Settings(BaseSettings):
    """平台全局配置模型。

    字段名与环境变量一一对应（大小写不敏感）；列表类复杂字段兼容 CSV 形式。
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 有效 .env 路径；None 表示 dotenv 被禁用（_env_file=None），在 __init__ 捕获。
    _dotenv_path: Path | None

    def __init__(
        self,
        _env_file: DotenvType | None = ENV_FILE_SENTINEL,
        **kwargs: object,
    ) -> None:
        super().__init__(_env_file=_env_file, **kwargs)  # type: ignore[arg-type]  # pydantic-settings 命名参数全部类型化，kwargs 转发 mypy 无法静态收窄
        self._dotenv_path = self._effective_env_file(_env_file)

    @staticmethod
    def _effective_env_file(_env_file: DotenvType | None) -> Path | None:
        """计算有效 .env 路径：_env_file=None 禁用 dotenv；否则回落 model_config 配置。"""
        if _env_file is None:
            return None
        if _env_file is not ENV_FILE_SENTINEL:
            # 显式传入的单路径（本项目仅使用单个 .env，Sequence 场景不涉及）
            if isinstance(_env_file, (str, Path)):
                return Path(_env_file)
            return None
        configured = Settings.model_config.get("env_file")
        if isinstance(configured, (str, Path)):
            return Path(configured)
        return None

    def resolve_secret(self, name: str) -> str | None:
        """按名称取密钥：真实环境变量优先，其次 .env 文件（不写入 os.environ）。

        与 pydantic-settings 优先级一致（环境变量 > .env 文件）；_env_file=None
        时只读真实环境变量，天然隔离测试进程。
        """
        value = os.environ.get(name)
        if value:
            return value
        if self._dotenv_path is None:
            return None
        return dotenv_values(self._dotenv_path).get(name)

    # ---- 路径 ----
    agents_root_dir: Path = Path("agents")
    mcp_registry_path: Path = Path("config/mcp-servers.yaml")
    llm_providers_path: Path = Path("config/llm-providers.yaml")
    agent_workspace_root_dir: Path = Path("workspaces")

    # ---- 持久化（PostgreSQL + SQLAlchemy async） ----
    # 连接参数分字段配置（DB_USERNAME / DB_PASSWORD / DB_HOST / DB_PORT /
    # DB_DATABASE），database_url 由这些字段组装。默认值用 127.0.0.1 而非
    # localhost：Windows + Docker 下 localhost 先解析为 IPv6 ::1，
    # 其回环转发超时（~21s），强制 IPv4 规避。
    db_username: str = "postgres"
    db_password: str = "postgres"
    db_host: str = "127.0.0.1"
    db_port: int = 5432
    db_database: str = "agent_platform"

    @property
    def database_url(self) -> str:
        """SQLAlchemy 异步连接串（asyncpg 驱动），由 DB_* 字段组装。"""
        return (
            "postgresql+asyncpg://"
            f"{quote_plus(self.db_username)}:{quote_plus(self.db_password)}"
            f"@{self.db_host}:{self.db_port}/{self.db_database}"
        )

    # ---- 存储（Blob Engine：字节流入存储层，元数据入库） ----
    storage_root_dir: Path = Path("storage")

    # ---- LLM ----
    default_provider_id: str = "qwen3.7-max"
    thinking_enabled: bool = True
    llm_connect_timeout_seconds: float = 10.0
    llm_read_timeout_seconds: float = 60.0
    llm_total_timeout_seconds: float = 300.0
    error_message_max_chars: int = 500

    # ---- 打字机（正文） ----
    typewriter_frame_interval_ms: int = 30
    typewriter_chars_per_frame: int = 2
    typewriter_catchup_threshold: int = 200
    typewriter_catchup_ratio: int = 4

    # ---- 打字机（思考） ----
    thinking_frame_interval_ms: int = 20
    thinking_chars_per_frame: int = 4

    # ---- SSE ----
    sse_heartbeat_interval_seconds: float = 15.0
    sse_queue_max_events: int = 128

    # ---- 控制台客户端 ----
    console_base_url: str = "http://127.0.0.1:8000"
    console_char_delay_ms: int = 20
    console_request_timeout_seconds: float = 300.0

    # ---- 工具 ----
    tool_batch_concurrency: int = 10
    tool_default_timeout_seconds: float = 30.0
    tool_output_truncate_chars: int = 6000
    tool_log_root_dir: Path = Path("logs/tools")
    tool_log_retention_days: int = 7
    tool_log_max_files_per_session: int = 200

    # ---- 脚本执行（本地直跑） ----
    # pragma: 简化 — 可信内部脚本，P1 一律宿主 subprocess 直跑，不做容器隔离；
    # 若将来对外开放脚本编辑，再引入轻量沙箱（2026-08 用户决策）。
    script_timeout_seconds: float = 120.0
    script_stream_limit_chars: int = 100_000
    script_stderr_tail_chars: int = 2000
    script_terminate_grace_seconds: float = 1.0

    # ---- 会话与产物 ----
    artifact_max_size_bytes: int = 100 * 1024 * 1024
    # 会话标题：首回合取首条 query 截断的最大长度
    conversation_name_max_chars: int = 50

    # ---- 文件上传（/files API） ----
    storage_upload_file_size_limit_mb: int = 20
    storage_upload_allowed_extensions: str = "png,jpg,jpeg,gif,webp,pdf,docx,xlsx,csv,md,txt"

    # ---- 推理 ----
    context_budget_tokens: int = 96000
    reasoning_max_turns: int = 40

    # ---- 会话记忆（L1：历史上下文恢复） ----
    # 续聊恢复上下文时从 messages 加载的最近回合上限（条）
    history_max_messages: int = 50

    # ---- 装配（智能体清单） ----
    agent_body_max_chars: int = 2000
    skill_body_max_chars: int = 8000

    # ---- 功能开关（{module}_enabled 命名） ----
    hot_reload_enabled: bool = False
    hot_reload_interval_seconds: float = 30.0

    # ---- 插件开关（{plugin}_enabled 命名，插件系统统一加载） ----
    # Redis 无开关恒启用：认证会话层硬依赖（登录会话 / 令牌过期 / 撤销 / 续期以 Redis 为准）
    logging_enabled: bool = True
    db_enabled: bool = True
    storage_enabled: bool = True
    mcp_enabled: bool = True
    llm_enabled: bool = True

    # ---- logging 扩展 ----
    # 输出格式："text" 明文行 / "json" 结构化单行
    log_output_format: Literal["text", "json"] = "text"
    # 日志时区（IANA 名称）
    log_tz: str = DEFAULT_LOG_TZ
    # 日志目录与文件名（RotatingFileHandler，log_file_max_size 单位为 MB）
    log_dir: str = "logs"
    log_file: str = "app.log"
    log_file_max_size: int = 10
    log_file_backup_count: int = 5
    # 模块级日志级别覆盖：{logger 名: 级别}，如 {"app.tools.broker": "DEBUG"}
    log_module_levels: dict[str, str] = {}

    # ---- redis 插件 ----
    redis_url: str = "redis://127.0.0.1:6379/0"
    redis_cache_default_ttl_seconds: int = 3600
    redis_lock_default_timeout_seconds: float = 30.0

    # ---- storage 插件 ----
    # 存储后端："local" 本地磁盘；"s3" 为后续扩展点（本次未实现）
    storage_backend: Literal["local", "s3"] = "local"

    # ---- 中间件 ----
    # 请求日志中间件开关（全局异常中间件始终启用，替换内联异常处理器）
    request_logging_enabled: bool = True

    # ---- 服务 ----
    log_level: str = "INFO"
    host: str = "0.0.0.0"
    port: int = 8000

    # ---- 账号认证（JWT + Argon2id + Redis 会话层） ----
    # JWT 签名密钥：必须从环境注入，无默认有效值（缺失时 JwtService 构造抛 ConfigError）
    jwt_secret_key: str = ""
    jwt_algorithm: str = "HS256"
    # 访问令牌有效期（秒）：JWT exp 与 Redis 访问会话 TTL 对齐（Redis 为准，key 缺失即
    # 登录失效）。短期令牌，到期后前端经 /auth/refresh 用刷新令牌续期。
    auth_access_token_ttl_seconds: int = 60 * 60 * 24
    # 刷新令牌有效期（秒）：Redis 刷新会话 TTL（权威）。到期 / 被轮换 / 登出即需重新登录。
    auth_refresh_token_ttl_seconds: int = 60 * 60 * 24 * 7
    # Argon2id 参数（OWASP 推荐强度：64 MiB、3 次迭代、4 并行）
    argon2_time_cost: int = 3
    argon2_memory_cost: int = 65536
    argon2_parallelism: int = 4
    # 修改密码时新密码最短长度（前端预校验同源经 env 注入）
    account_password_min_length: int = 8

    # ---- 账号头像（/users/me/avatar） ----
    # 头像显示目标：侧栏 32px / 资料弹窗 ~96px 圆形；限制以「够用且轻」为度。
    # 大小上限（字节，2 MiB）：圆形小图无需原图，防超大文件占存储。
    avatar_max_size_bytes: int = 2 * 1024 * 1024
    # 允许的图片扩展名（服务端同时做 magic bytes 内容校验，防改名伪装）
    avatar_allowed_extensions: str = "png,jpg,jpeg,webp,gif"
    # 边长上限（像素）：超出即压缩也无意义（显示目标 ≤96px，512 已足）
    avatar_max_dimension: int = 512
    # 边长下限（像素）：低于侧栏展示尺寸会模糊
    avatar_min_dimension: int = 32

    # ---- 公司统一登录（elecnest SSO） ----
    # 开关：默认开启（平台以公司统一登录为主）；关闭时 /auth/login/elecnest 返回 400（未启用）
    elecnest_sso_enabled: bool = True
    # 统一登录用户信息接口（token + uid → 用户资料；全量参数见 API 文档）
    elecnest_get_user_info_url: str = "https://id.elecnest.cn/api/login/getUserInfo"
    # 外部 HTTP 调用超时（秒）
    elecnest_sso_timeout_seconds: float = 10.0


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """进程级配置单例（首次调用后缓存）。热重载场景需显式重建。"""
    return Settings()
