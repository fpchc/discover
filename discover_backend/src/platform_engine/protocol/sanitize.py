"""事件载荷脱敏：工具参数摘要与错误消息在推送前完成替换。

sse-streaming-spec §9：工具参数摘要按键名匹配敏感词（令牌、密钥、口令、
认证、凭据类）替换值；错误消息不含完整命令行、环境变量值、请求体。
"""

import re

_JSON_PAIR_RE = re.compile(
    r'("(?:token|secret|password|passwd|credential|api[_-]?key|authorization|bearer)"'
    r'\s*:\s*)(?:"[^"]*"|[^\s,}\]]+)',
    re.IGNORECASE,
)

_ENV_PAIR_RE = re.compile(
    r"(\b[A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|API[_-]?KEY)[A-Z0-9_]*\s*=\s*)[^\s,;\"']+",
    re.IGNORECASE,
)

_REDACTED = "***"
_ELLIPSIS = "…(截断)"


def truncate(text: str, *, max_length: int) -> str:
    """按字符截断，保留头部（API 关键字段通常在前），追加截断标识。"""
    if len(text) <= max_length:
        return text
    return text[:max_length] + _ELLIPSIS


def redact_sensitive(text: str) -> str:
    """替换敏感键（令牌/密钥/口令/认证类）的值为遮蔽符。"""
    redacted = _JSON_PAIR_RE.sub(rf"\1{_REDACTED}", text)
    redacted = _ENV_PAIR_RE.sub(rf"\1{_REDACTED}", redacted)
    return redacted


def sanitize_tool_args(summary: str, *, max_length: int) -> str:
    """工具参数摘要脱敏 + 截断。"""
    return redact_sensitive(truncate(summary, max_length=max_length))


def sanitize_error_message(message: str, *, max_length: int) -> str:
    """错误消息脱敏 + 截断。"""
    return redact_sensitive(truncate(message, max_length=max_length))
