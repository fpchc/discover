"""领域异常体系。

异常携带错误分类（ErrorCategory）与可重试性标记（retryable）。
错误信息传递前必须脱敏：不含密钥、不含完整请求体、不含环境变量值。
"""

from enum import StrEnum


class ErrorCategory(StrEnum):
    """错误分类，供上层决定展示与处理策略。"""

    CONFIG = "config"
    CONNECTION = "connection"
    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"
    SERVER = "server"
    AUTH = "auth"
    BAD_REQUEST = "bad_request"
    CONTENT_FILTER = "content_filter"
    STREAM_INTERRUPTED = "stream_interrupted"
    NOT_FOUND = "not_found"
    INVALID_ARGUMENT = "invalid_argument"
    DENIED = "denied"
    SCRIPT = "script"
    MCP = "mcp"


def http_status_for(category: ErrorCategory) -> int:
    """领域错误分类 → HTTP 状态码（API 层共用，避免本地重复映射）。"""
    mapping = {
        ErrorCategory.NOT_FOUND: 404,
        ErrorCategory.INVALID_ARGUMENT: 400,
        ErrorCategory.AUTH: 401,
        ErrorCategory.DENIED: 403,
        ErrorCategory.BAD_REQUEST: 400,
        ErrorCategory.CONFIG: 500,
    }
    return mapping.get(category, 500)


class PlatformError(Exception):
    """领域异常基类。"""

    category: ErrorCategory
    retryable: bool

    def __init__(
        self,
        message: str,
        *,
        category: ErrorCategory | None = None,
        retryable: bool | None = None,
    ) -> None:
        super().__init__(message)
        self.category = category if category is not None else ErrorCategory.SERVER
        self.retryable = retryable if retryable is not None else False


class ConfigError(PlatformError):
    """配置或注册表加载 / 校验失败。不可重试，需修正配置。"""

    def __init__(self, message: str) -> None:
        super().__init__(message, category=ErrorCategory.CONFIG, retryable=False)


class RegistryValidationError(PlatformError):
    """智能体 / 技能清单加载期校验失败。不影响其他智能体加载。"""

    def __init__(self, message: str) -> None:
        super().__init__(message, category=ErrorCategory.BAD_REQUEST, retryable=False)


class NotFoundError(PlatformError):
    """资源不存在（未知智能体 / 产物等）。HTTP 404。"""

    def __init__(self, message: str) -> None:
        super().__init__(message, category=ErrorCategory.NOT_FOUND, retryable=False)


class UnauthorizedError(PlatformError):
    """未认证 / 令牌无效过期（账号体系）。HTTP 401。"""

    def __init__(self, message: str) -> None:
        super().__init__(message, category=ErrorCategory.AUTH, retryable=False)


class ForbiddenError(PlatformError):
    """认证通过但无权限（如非超级用户访问管理接口）。HTTP 403。"""

    def __init__(self, message: str) -> None:
        super().__init__(message, category=ErrorCategory.DENIED, retryable=False)


class LLMError(PlatformError):
    """LLM 客户端错误基类。"""


class LLMConnectionError(LLMError):
    """连接失败。网络层问题，可重试。"""

    def __init__(self, message: str) -> None:
        super().__init__(message, category=ErrorCategory.CONNECTION, retryable=True)


class LLMTimeoutError(LLMError):
    """超时（连接超时 / 分片间隔超时 / 总时长上限）。可重试。"""

    def __init__(self, message: str) -> None:
        super().__init__(message, category=ErrorCategory.TIMEOUT, retryable=True)


class LLMRateLimitError(LLMError):
    """限流。可重试，需按提供方返回的等待提示退避。"""

    def __init__(self, message: str) -> None:
        super().__init__(message, category=ErrorCategory.RATE_LIMIT, retryable=True)


class LLMServerError(LLMError):
    """服务端错误（5xx）。可有限重试。"""

    def __init__(self, message: str) -> None:
        super().__init__(message, category=ErrorCategory.SERVER, retryable=True)


class LLMAuthError(LLMError):
    """鉴权失败。配置问题，重试无意义。"""

    def __init__(self, message: str) -> None:
        super().__init__(message, category=ErrorCategory.AUTH, retryable=False)


class LLMBadRequestError(LLMError):
    """请求非法（参数或上下文超限）。需修正后重试。"""

    def __init__(self, message: str) -> None:
        super().__init__(message, category=ErrorCategory.BAD_REQUEST, retryable=False)


class LLMContentFilterError(LLMError):
    """内容过滤。需调整输入。"""

    def __init__(self, message: str) -> None:
        super().__init__(message, category=ErrorCategory.CONTENT_FILTER, retryable=False)


class LLMStreamInterruptedError(LLMError):
    """流中断。已产出部分内容时不可简单重试（会导致重复输出）。"""

    def __init__(self, message: str) -> None:
        super().__init__(message, category=ErrorCategory.STREAM_INTERRUPTED, retryable=False)


class ToolError(PlatformError):
    """工具层错误基类。"""


class ToolNotFoundError(ToolError):
    """工具不在目录。应返回最近似候选供模型选择。"""

    def __init__(self, message: str) -> None:
        super().__init__(message, category=ErrorCategory.NOT_FOUND, retryable=False)


class ToolInvalidArgumentError(ToolError):
    """参数不符约束。应附该工具完整约束供修正。"""

    def __init__(self, message: str) -> None:
        super().__init__(message, category=ErrorCategory.INVALID_ARGUMENT, retryable=False)


class ToolTimeoutError(ToolError):
    """单工具超时。建议缩小输入或分批。"""

    def __init__(self, message: str) -> None:
        super().__init__(message, category=ErrorCategory.TIMEOUT, retryable=False)


class ToolServiceError(ToolError):
    """上游服务进程崩溃或服务错误。建议走降级通道。"""

    def __init__(self, message: str) -> None:
        super().__init__(message, category=ErrorCategory.SERVER, retryable=False)


class ToolDeniedError(ToolError):
    """审批被拒。消息为“用户拒绝该操作”。"""

    def __init__(self, message: str) -> None:
        super().__init__(message, category=ErrorCategory.DENIED, retryable=False)


class MCPError(PlatformError):
    """MCP 客户端错误基类。"""


class MCPAuthError(MCPError):
    """MCP 认证失败（HTTP 401/403）。配置问题，重试无意义。"""

    def __init__(self, message: str) -> None:
        super().__init__(message, category=ErrorCategory.AUTH, retryable=False)


class MCPTimeoutError(MCPError):
    """MCP 调用超时。可重试，建议缩小查询范围。"""

    def __init__(self, message: str) -> None:
        super().__init__(message, category=ErrorCategory.TIMEOUT, retryable=True)


class MCPConnectionError(MCPError):
    """MCP 连接失败。网络层问题，可重试。"""

    def __init__(self, message: str) -> None:
        super().__init__(message, category=ErrorCategory.CONNECTION, retryable=True)


class MCPRateLimitError(MCPError):
    """MCP 上游限流（HTTP 429）。可重试，需退避。"""

    def __init__(self, message: str) -> None:
        super().__init__(message, category=ErrorCategory.RATE_LIMIT, retryable=True)


class MCPServiceError(MCPError):
    """MCP 服务端错误（HTTP 5xx / JSON-RPC 错误 / 工具级错误）。"""

    def __init__(self, message: str) -> None:
        super().__init__(message, category=ErrorCategory.SERVER, retryable=True)


class MCPInvalidArgumentError(MCPError):
    """MCP 请求参数非法（HTTP 400 / JSON-RPC -32602）。需调整参数。"""

    def __init__(self, message: str) -> None:
        super().__init__(message, category=ErrorCategory.INVALID_ARGUMENT, retryable=False)


class ScriptError(PlatformError):
    """脚本容器执行错误基类。"""


class SessionError(PlatformError):
    """会话层错误基类。"""


class SessionNotFoundError(SessionError):
    """会话标识不存在。不可重试。"""

    def __init__(self, message: str) -> None:
        super().__init__(message, category=ErrorCategory.NOT_FOUND, retryable=False)


class BadRequestError(SessionError):
    """请求非法（上传/输入校验失败）。HTTP 400。

    继承 SessionError 以便既有 `raises(SessionError)` 断言兼容。
    """

    def __init__(self, message: str) -> None:
        super().__init__(message, category=ErrorCategory.BAD_REQUEST, retryable=False)
