"""日志扩展：生产可用的非阻塞结构化日志。

QueueHandler + QueueListener 异步落盘（不阻塞调用线程）；text/json 两种
结构化输出共享同一字段载荷；SensitiveDataFilter 脱敏、TraceFilter 注入
trace_id、模块级级别覆盖（均来自 app.infrastructure.logging.logging）。init_app 在事件循环
启动前（同步阶段）建好监听线程；shutdown 排空并释放。
"""

from __future__ import annotations

import copy
import gzip
import json
import logging
import logging.handlers
import os
import re
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, tzinfo
from pathlib import Path
from queue import Queue
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import FastAPI

from app.config.settings import DEFAULT_LOG_TZ, active_settings
from app.infrastructure.logging.logging import (
    SensitiveDataFilter,
    TraceFilter,
    apply_module_levels,
    resolve_level,
)

logger = logging.getLogger(__name__)

_RESERVED_ATTRS = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
        "trace_id",
    }
)


class _StructuredFormatter(logging.Formatter):
    """为文本与 JSON 输出构造相同的结构化字段。"""

    def __init__(self, timezone: tzinfo) -> None:
        super().__init__()
        self._timezone = timezone

    def _build_payload(self, record: logging.LogRecord) -> dict[str, object]:
        extra = {key: value for key, value in record.__dict__.items() if key not in _RESERVED_ATTRS}
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=self._timezone).strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            "level": record.levelname,
            "trace_id": getattr(record, "trace_id", "-"),
            "logger": record.name,
            "execution": f"P:{record.process}:T:{record.thread}",
            "location": f"{record.filename}:{record.lineno}",
            "message": record.getMessage(),
            "extra": extra,
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return payload


class _JsonFormatter(_StructuredFormatter):
    """结构化单行 JSON。"""

    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(self._build_payload(record), ensure_ascii=False, default=str)


class _TextFormatter(_StructuredFormatter):
    """明文 key=value 行（extra 以 JSON 呈现）。"""

    def format(self, record: logging.LogRecord) -> str:
        payload = self._build_payload(record)
        fields = (
            f"timestamp={payload['timestamp']}",
            f"level={payload['level']}",
            f"trace_id={payload['trace_id']}",
            f"logger={payload['logger']}",
            f"execution={payload['execution']}",
            f"location={payload['location']}",
            f"message={payload['message']}",
            f"extra={json.dumps(payload['extra'], ensure_ascii=False, default=str)}",
        )
        line = " ".join(fields)
        exc_info = payload.get("exc_info")
        return f"{line}\n{exc_info}" if exc_info else line


class _PreservingQueueHandler(logging.handlers.QueueHandler):
    """跨线程传递日志，同时保留结构化异常信息。"""

    def prepare(self, record: logging.LogRecord) -> logging.LogRecord:
        prepared = copy.copy(record)
        prepared.msg = record.getMessage()
        prepared.args = None
        return prepared


class _TimedCompressedRotatingFileHandler(logging.handlers.TimedRotatingFileHandler):
    """按时间轮转 + gzip 压缩归档的生产级文件日志 handler。

    轮转出的旧文件（如 app.log.2026-09-03）在落盘后立即压缩为 .gz；
    backupCount 清理同时覆盖未压缩与已压缩归档，避免 .gz 无限堆积。
    """

    def __init__(
        self,
        filename: str | os.PathLike[str],
        *,
        when: str = "midnight",
        interval: int = 1,
        backupCount: int = 0,
        encoding: str | None = None,
        utc: bool = False,
        atTime: datetime | None = None,
        compress: bool = True,
    ) -> None:
        self._compress = compress
        super().__init__(
            filename,
            when=when,
            interval=interval,
            backupCount=backupCount,
            encoding=encoding,
            utc=utc,
            atTime=atTime,
        )
        self._archive_pattern = self._build_archive_pattern()

    def _build_archive_pattern(self) -> re.Pattern[str]:
        """由 self.suffix（如 %Y-%m-%d）构造匹配归档名的正则，兼容 .gz 后缀。"""
        token_patterns = {
            "%Y": r"\d{4}",
            "%m": r"\d{2}",
            "%d": r"\d{2}",
            "%H": r"\d{2}",
            "%M": r"\d{2}",
            "%S": r"\d{2}",
        }
        parts = re.split(r"(%[YmdHMS])", self.suffix)
        expr = "".join(token_patterns.get(part, re.escape(part)) for part in parts)
        return re.compile(rf"^{expr}(?:\.gz)?$")

    def rotate(self, source: str, dest: str) -> None:
        super().rotate(source, dest)
        if not self._compress or not os.path.exists(dest):
            return
        archive = f"{dest}.gz"
        with open(dest, "rb") as src_fp, gzip.open(archive, "wb") as dst_fp:
            shutil.copyfileobj(src_fp, dst_fp)
        os.remove(dest)

    def getFilesToDelete(self) -> list[str]:
        if self.backupCount <= 0:
            return []
        dir_name, base_name = os.path.split(self.baseFilename)
        prefix = f"{base_name}."
        candidates = [
            os.path.join(dir_name, name)
            for name in os.listdir(dir_name)
            if name.startswith(prefix) and self._archive_pattern.fullmatch(name[len(prefix) :])
        ]
        candidates.sort()
        if len(candidates) <= self.backupCount:
            return []
        return candidates[: len(candidates) - self.backupCount]


@dataclass(frozen=True, slots=True)
class _LoggingRuntime:
    listener: logging.handlers.QueueListener
    queue_handler: logging.handlers.QueueHandler
    output_handlers: tuple[logging.Handler, ...]


_runtime: _LoggingRuntime | None = None


def is_enabled() -> bool:
    """由配置开关控制（默认开启；测试可关闭，避免替换根 logger 破坏日志捕获）。"""
    return active_settings().logging_enabled


def _resolve_timezone(timezone_name: str) -> tzinfo:
    name = timezone_name.strip() or DEFAULT_LOG_TZ
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        msg = f"Unsupported LOG_TZ: {timezone_name!r}"
        raise ValueError(msg) from exc


def _build_formatter() -> logging.Formatter:
    settings = active_settings()
    output_format = settings.log_output_format.lower()
    timezone = _resolve_timezone(settings.log_tz)
    if output_format == "json":
        return _JsonFormatter(timezone)
    return _TextFormatter(timezone)


def _build_output_handlers(level: int) -> tuple[logging.Handler, ...]:
    formatter = _build_formatter()
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(formatter)
    handlers: list[logging.Handler] = [console]
    handlers.append(_build_file_handler(level, formatter))
    for handler in handlers:
        handler.addFilter(SensitiveDataFilter())
    return tuple(handlers)


def _build_file_handler(level: int, formatter: logging.Formatter) -> logging.Handler:
    settings = active_settings()
    log_dir = Path(settings.log_dir.strip())
    log_file = Path(settings.log_file.strip())
    if not settings.log_dir.strip() or not settings.log_file.strip():
        msg = "LOG_DIR and LOG_FILE must not be empty"
        raise ValueError(msg)
    if log_file.is_absolute() or log_file.name != str(log_file):
        msg = "LOG_FILE must be a file name without directory components"
        raise ValueError(msg)
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = _TimedCompressedRotatingFileHandler(
        log_dir / log_file,
        when=settings.log_rotation_when,
        interval=settings.log_rotation_interval,
        backupCount=settings.log_file_backup_count,
        encoding="utf-8",
        compress=settings.log_compress,
    )
    handler.setLevel(level)
    handler.setFormatter(formatter)
    return handler


def _close_runtime(runtime: _LoggingRuntime) -> None:
    root = logging.getLogger()
    if runtime.queue_handler in root.handlers:
        root.removeHandler(runtime.queue_handler)
    runtime.listener.stop()
    runtime.queue_handler.close()
    for handler in runtime.output_handlers:
        handler.close()


def _replace_root_handlers(handler: logging.Handler, level: int) -> None:
    root = logging.getLogger()
    previous_handlers = tuple(root.handlers)
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
    for previous_handler in previous_handlers:
        previous_handler.close()


def _start_runtime(output_handlers: tuple[logging.Handler, ...], level: int) -> _LoggingRuntime:
    log_queue: Queue[logging.LogRecord] = Queue()
    queue_handler = _PreservingQueueHandler(log_queue)
    queue_handler.addFilter(TraceFilter())
    listener = logging.handlers.QueueListener(
        log_queue, *output_handlers, respect_handler_level=True
    )
    listener_started = False
    try:
        listener.start()
        listener_started = True
        _replace_root_handlers(queue_handler, level)
    except Exception:
        if listener_started:
            listener.stop()
        queue_handler.close()
        for handler in output_handlers:
            handler.close()
        raise
    return _LoggingRuntime(listener, queue_handler, output_handlers)


def init_app(app: FastAPI | None) -> None:
    """在事件循环启动前初始化日志处理线程。"""
    global _runtime

    if _runtime is not None:
        _close_runtime(_runtime)
        _runtime = None

    settings = active_settings()
    level = resolve_level(settings.log_level)
    output_handlers = _build_output_handlers(level)
    _runtime = _start_runtime(output_handlers, level)
    if app is not None:
        app.state.log_listener = _runtime.listener
    apply_module_levels(settings)
    logger.info(
        "Logging initialized",
        extra={"level": settings.log_level, "format": settings.log_output_format},
    )


async def startup(app: FastAPI) -> None:
    """日志已在同步初始化阶段启动。"""


async def shutdown(app: FastAPI | None) -> None:
    """排空日志队列并释放所有日志资源。"""
    global _runtime

    if _runtime is None:
        return
    logger.info("Logging shutdown")
    _close_runtime(_runtime)
    _runtime = None
    if app is not None:
        app.state.log_listener = None
