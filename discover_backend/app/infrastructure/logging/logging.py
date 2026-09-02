"""日志内核：日志过滤器、trace 上下文与模块级别控制。

供 extensions.ext_logging 与业务侧共享：SensitiveDataFilter 脱敏敏感字段、
TraceFilter 注入 trace_id（ContextVar）、apply_module_levels 做模块级级别覆盖。
"""

from __future__ import annotations

import logging
import re
from contextvars import ContextVar

from app.config.settings import Settings

_SENSITIVE_RE = re.compile(
    r"(\b(?:token|secret|password|passwd|credential|api[_-]?key|authorization|bearer)"
    r"\b\s*[=:]\s*)\S+",
    re.IGNORECASE,
)

_TRACE_ID: ContextVar[str] = ContextVar("trace_id", default="-")


def set_trace_id(trace_id: str) -> None:
    """为当前任务（ContextVar 传播范围）设置 trace_id。"""
    _TRACE_ID.set(trace_id)


def get_trace_id() -> str:
    """取当前任务 trace_id；未设置时为 "-"。"""
    return _TRACE_ID.get()


def resolve_level(level_name: str) -> int:
    """日志级别名 → 整数；非法名抛 ValueError。"""
    level = logging.getLevelNamesMapping().get(level_name.upper())
    if level is None:
        raise ValueError(f"Unsupported log level: {level_name!r}")
    return level


class SensitiveDataFilter(logging.Filter):
    """脱敏记录：消息文本与结构化 extra 字段中的敏感键值。

    消息文本匹配 `token=值` 形式；extra 结构化字段按敏感键名（token/secret/
    password/api_key/bearer 等）整值遮蔽，防结构化日志泄露密钥。
    """

    _SENSITIVE_KEY_RE = re.compile(
        r"(token|secret|password|passwd|credential|api[_-]?key|authorization|bearer)",
        re.IGNORECASE,
    )

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _SENSITIVE_RE.sub(r"\1***", record.getMessage())
        record.args = ()
        for key, value in record.__dict__.items():
            if self._SENSITIVE_KEY_RE.search(key) and isinstance(value, str):
                setattr(record, key, "***")
        return True


class TraceFilter(logging.Filter):
    """把当前任务 trace_id 注入记录，供结构化格式器取用。"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = _TRACE_ID.get()
        return True


def apply_module_levels(settings: Settings) -> None:
    """按配置 {logger 名: 级别} 覆盖模块级日志级别。"""
    for name, level_name in settings.log_module_levels.items():
        logging.getLogger(name).setLevel(resolve_level(level_name))
