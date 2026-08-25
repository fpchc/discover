"""logging 插件：统一配置日志输出（控制台必选 + 文件可选）。

log_format="text" 输出明文行（含结构化字段 key=value 追加），="json" 输出
结构化单行 JSON。根 logger 已有 handler（如 pytest 注入的捕获 handler）时
跳过配置，避免 clobber 测试日志；文件落盘目录先建（async 路径经 anyio 线程池）。
"""

from __future__ import annotations

import json
import logging
import logging.handlers
from datetime import UTC, datetime

import anyio

from app.config.settings import Settings
from app.plugins.base import Plugin, register

_LOG_FMT_TEXT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_LOG_ROTATE_BYTES = 10 * 1024 * 1024
_LOG_ROTATE_BACKUPS = 5


def structured(**fields: object) -> dict[str, object]:
    """构造结构化日志字段（经 extra 注入 record，两种格式器均可消费）。"""
    return {"extra_fields": fields}


class _JsonFormatter(logging.Formatter):
    """结构化单行 JSON 格式器。"""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        extra = getattr(record, "extra_fields", None)
        if isinstance(extra, dict):
            payload.update(extra)
        if record.exc_info is not None:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


class _TextFormatter(logging.Formatter):
    """明文行格式器：结构化字段以 key=value 追加。"""

    def __init__(self) -> None:
        super().__init__(fmt=_LOG_FMT_TEXT)

    def format(self, record: logging.LogRecord) -> str:
        line = super().format(record)
        extra = getattr(record, "extra_fields", None)
        if isinstance(extra, dict) and extra:
            line += " " + " ".join(f"{k}={v}" for k, v in extra.items())
        return line


def _formatter_for(settings: Settings) -> type[logging.Formatter]:
    if settings.log_format == "json":
        return _JsonFormatter
    return _TextFormatter


def _configure_root(settings: Settings) -> None:
    """为根 logger 配置控制台与可选文件 handler（已有 handler 时跳过）。"""
    root = logging.getLogger()
    if root.handlers:
        return
    formatter = _formatter_for(settings)()
    root.setLevel(settings.log_level)
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)
    if settings.log_dir is not None:
        settings.log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            settings.log_dir / "app.log",
            maxBytes=_LOG_ROTATE_BYTES,
            backupCount=_LOG_ROTATE_BACKUPS,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)


@register
class LoggingPlugin(Plugin):
    """日志配置插件：副作用型（无客户端），统一根 logger 输出。"""

    name = "logging"

    @classmethod
    def is_enabled(cls, settings: Settings) -> bool:
        return settings.logging_enabled

    async def startup(self) -> None:
        await anyio.to_thread.run_sync(_configure_root, self._settings)

    async def shutdown(self) -> None:
        """日志无需显式释放。"""
